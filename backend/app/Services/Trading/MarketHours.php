<?php

namespace App\Services\Trading;

use App\Enums\ConnectorType;
use App\Models\BrokerSymbol;
use App\Models\TradingAccount;
use Carbon\CarbonImmutable;
use Illuminate\Support\Facades\DB;

/**
 * Is a symbol's market open right now on an account — and if not, until when?
 *
 * Mirrors the engine (`market_data/sessions.py`): forex trades from Sunday
 * 21:00 to Friday 21:00 UTC; synthetic indices (R_10 … R_100, 1HZ…) trade
 * around the clock; anything else follows what the broker last reported
 * (`broker_symbols.market_open`). Paper accounts run on simulated time, so
 * their clock is the simulation's cursor, not the wall clock.
 */
class MarketHours
{
    private const FX_OPEN_HOUR = 21; // Sunday open and Friday close, UTC

    /**
     * Null when open (or unknown), otherwise {symbol, reopens_at (UTC|null), simulated}.
     *
     * @return array{symbol: string, reopens_at: ?CarbonImmutable, simulated: bool}|null
     */
    public function closed(TradingAccount $account, string $symbol): ?array
    {
        $account->loadMissing('connection');
        $row = BrokerSymbol::query()->where('connection_id', $account->connection_id)
            ->where(fn ($q) => $q->where('name', $symbol)->orWhere('canonical', $symbol))
            ->orderByRaw('name = ? desc', [$symbol])->first();
        $category = $row?->category ?? self::guessCategory($symbol);
        $paper = $account->connection?->connector_type === ConnectorType::Paper;
        $brokerSaysClosed = $row !== null && $row->market_open === false;

        if ($category === 'forex') {
            $simulated = $paper ? $this->paperClock($account) : null;
            $now = $simulated ?? CarbonImmutable::now('UTC');
            if (! self::fxOpen($now)) {
                return ['symbol' => $symbol, 'reopens_at' => self::fxReopens($now), 'simulated' => $simulated !== null];
            }
        }
        if ($brokerSaysClosed && ! $paper) {
            return ['symbol' => $symbol, 'reopens_at' => null, 'simulated' => false];
        }

        return null;
    }

    public static function fxOpen(CarbonImmutable $t): bool
    {
        $t = $t->utc();

        return match ($t->dayOfWeekIso) {
            6 => false,                                   // Saturday
            5 => $t->hour < self::FX_OPEN_HOUR,           // Friday until 21:00
            7 => $t->hour >= self::FX_OPEN_HOUR,          // Sunday from 21:00
            default => true,
        };
    }

    /** The next Sunday 21:00 UTC at or after a closed moment. */
    public static function fxReopens(CarbonImmutable $t): CarbonImmutable
    {
        $t = $t->utc();
        $sunday = $t->dayOfWeekIso === 7 ? $t->startOfDay() : $t->next(CarbonImmutable::SUNDAY);

        return $sunday->setTime(self::FX_OPEN_HOUR, 0);
    }

    /** forex | synthetic | null (unknown) from the symbol's name alone. */
    public static function guessCategory(string $symbol): ?string
    {
        $s = strtoupper($symbol);
        if (preg_match('/^(R_\d+|1HZ\d+V|JD\d+|BOOM\d+N?|CRASH\d+N?|STPRNG\d*|RDBULL|RDBEAR)$/', $s)) {
            return 'synthetic';
        }
        if (preg_match('/^(FRX)?(EUR|GBP|USD|JPY|AUD|NZD|CAD|CHF){2}$/', $s)) {
            return 'forex';
        }

        return null;
    }

    /** The Paper simulation's "now" (its cursor), when the engine has saved one. */
    private function paperClock(TradingAccount $account): ?CarbonImmutable
    {
        $raw = DB::table('paper_states')->where('connection_id', $account->connection_id)->value('state');
        $state = is_string($raw) ? json_decode($raw, true) : null;
        $cursor = is_array($state) ? ($state['market']['cursor'] ?? null) : null;
        if (! is_string($cursor)) {
            return null;
        }
        try {
            return CarbonImmutable::parse($cursor)->utc();
        } catch (\Throwable) {
            return null;
        }
    }
}
