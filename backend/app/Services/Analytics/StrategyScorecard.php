<?php

namespace App\Services\Analytics;

use App\Models\Trade;
use App\Models\TradingAccount;
use Illuminate\Support\Collection;

/**
 * How each strategy is really doing on one account, from its closed trades:
 * win rate against the win rate it NEEDS to break even, profit per trade,
 * and a verdict that does not mistake a lucky run for an edge.
 *
 * Rows are one strategy on one symbol and contract family, because the same
 * strategy can make money on one market and lose on another.
 */
class StrategyScorecard
{
    /** Fewer closed trades than this says nothing either way. */
    public const MIN_TRADES = 30;

    /** |mean / standard error| at or above this (≈ 95% confidence) counts as real. */
    public const Z_THRESHOLD = 2.0;

    /** @return list<array<string, mixed>> */
    public function for(TradingAccount $account): array
    {
        $rows = Trade::query()
            ->join('strategy_versions', 'trades.strategy_version_id', '=', 'strategy_versions.id')
            ->join('strategies', 'strategy_versions.strategy_id', '=', 'strategies.id')
            ->where('trades.account_id', $account->id)
            ->where('trades.status', 'CLOSED')
            ->whereNotNull('trades.net_pnl')
            ->orderBy('trades.exit_time')
            ->get(['trades.*', 'strategies.id as strategy_id', 'strategies.name as strategy_name']);

        return $rows
            ->groupBy(fn (Trade $t) => $t->strategy_id.'|'.$t->symbol.'|'.$t->contract_family)
            ->map(fn (Collection $group) => $this->row($group))
            ->sortBy([['net_pnl', 'desc'], ['trades', 'desc']])
            ->values()
            ->all();
    }

    /** @param Collection<int, Trade> $trades */
    private function row(Collection $trades): array
    {
        $first = $trades->first();
        $pnl = $trades->map(fn (Trade $t) => (float) $t->net_pnl)->values();
        $n = $pnl->count();
        $wins = $pnl->filter(fn ($v) => $v > 0);
        $losses = $pnl->filter(fn ($v) => $v < 0);
        $avgWin = $wins->isNotEmpty() ? $wins->avg() : null;
        $avgLoss = $losses->isNotEmpty() ? $losses->avg() : null;
        $mean = $pnl->avg();

        return [
            'strategy_id' => $first->strategy_id,
            'strategy' => $first->strategy_name,
            'symbol' => $first->symbol,
            'contract_family' => $first->contract_family,
            'trades' => $n,
            'wins' => $wins->count(),
            'losses' => $losses->count(),
            'win_rate' => round($wins->count() / $n * 100, 1),
            'break_even_win_rate' => $this->breakEven($trades, $avgWin, $avgLoss),
            'avg_win' => $avgWin !== null ? round($avgWin, 2) : null,
            'avg_loss' => $avgLoss !== null ? round($avgLoss, 2) : null,
            'expectancy' => round($mean, 4),
            'net_pnl' => round($pnl->sum(), 2),
            'first_trade_at' => $first->entry_time?->toIso8601String(),
            'last_trade_at' => $trades->last()->exit_time?->toIso8601String(),
            ...$this->verdict($pnl->all(), $mean),
        ];
    }

    /**
     * The win rate at which this row would make exactly nothing. Rise/Fall pays a
     * fixed amount, so it comes straight from stake / payout; otherwise from the
     * average win and loss so far. Null while there isn't enough to tell.
     *
     * @param  Collection<int, Trade>  $trades
     */
    private function breakEven(Collection $trades, ?float $avgWin, ?float $avgLoss): ?float
    {
        $priced = $trades->filter(fn (Trade $t) => $t->contract_family === 'RISE_FALL'
            && (float) $t->stake > 0 && (float) $t->payout > (float) $t->stake);
        if ($priced->isNotEmpty()) {
            return round($priced->avg(fn (Trade $t) => (float) $t->stake / (float) $t->payout) * 100, 1);
        }
        if ($avgWin === null || $avgLoss === null) {
            return null;
        }

        return round(-$avgLoss / ($avgWin - $avgLoss) * 100, 1);
    }

    /**
     * @param  list<float>  $pnl
     * @return array{verdict: string, verdict_text: string, confidence_z: float|null}
     */
    private function verdict(array $pnl, float $mean): array
    {
        $n = count($pnl);
        if ($n < self::MIN_TRADES) {
            return [
                'verdict' => 'TOO_EARLY',
                'verdict_text' => sprintf('Too early: %d of %d trades needed before the results mean anything.', $n, self::MIN_TRADES),
                'confidence_z' => null,
            ];
        }
        $variance = array_sum(array_map(fn ($v) => ($v - $mean) ** 2, $pnl)) / ($n - 1);
        $z = $variance > 0 ? $mean / sqrt($variance / $n) : ($mean <=> 0) * INF;

        [$verdict, $text] = match (true) {
            $z >= self::Z_THRESHOLD => ['PROFITABLE', 'Making money, and unlikely to be luck. Keep watching it.'],
            $z <= -self::Z_THRESHOLD => ['LOSING', 'Losing money, and unlikely to be bad luck. Stop this one.'],
            default => ['NO_EDGE', 'No proven edge: these results are what luck alone would give.'],
        };

        return ['verdict' => $verdict, 'verdict_text' => $text, 'confidence_z' => is_finite($z) ? round($z, 2) : null];
    }
}
