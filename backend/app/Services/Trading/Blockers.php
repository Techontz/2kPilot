<?php

namespace App\Services\Trading;

use App\Enums\AccountEnvironment;
use App\Enums\AssignmentStatus;
use App\Enums\ConnectionStatus;
use App\Enums\EngineState;
use App\Enums\TradingMode;
use App\Models\StrategyAssignment;
use App\Models\TradingAccount;
use App\Models\User;

/**
 * "Why would nothing trade on this account right now?" — in plain words.
 * Each blocker is {code, message}; an empty list means trades can be placed.
 */
class Blockers
{
    public function __construct(private readonly TradingControl $control, private readonly MarketHours $hours) {}

    /**
     * The user's and the platform's controls, as seen when a strategy is
     * switched on (codes: platform_halted, trading_stopped, mode_mismatch,
     * live_locked, account_trading_disabled, engine_offline).
     *
     * @return list<array{code: string, message: string}>
     */
    public function controls(User $user, TradingAccount $account, ?TradingStatus $status = null): array
    {
        $status ??= $this->control->status($user);
        $env = $account->environment;
        $mode = $status->user->trading_mode;
        $out = [];
        if ($status->platform->kill_switch_engaged) {
            $out[] = self::item('platform_halted', 'Trading is halted platform-wide by an administrator.');
        }
        if ($status->user->kill_switch_engaged) {
            $out[] = self::item('trading_stopped', 'Trading is stopped — press Start when you are ready.');
        }
        $permitted = $mode === TradingMode::Demo
            ? in_array($env, [AccountEnvironment::Paper, AccountEnvironment::Demo], true)
            : $env === AccountEnvironment::Live;
        if (! $permitted) {
            $out[] = self::item('mode_mismatch', "This {$env->value} account is not traded in {$mode->value} mode.");
        }
        if ($env === AccountEnvironment::Live && ($status->liveLocked || $status->user->live_authorized_at === null)) {
            $out[] = self::item('live_locked', 'LIVE trading is locked or not authorised.');
        }
        if (! $account->trading_enabled) {
            $out[] = self::item('account_trading_disabled', 'Trading is switched off for this account (Accounts page).');
        }
        if ($status->engine === EngineState::Offline) {
            $out[] = self::item('engine_offline', 'The trading engine is offline.');
        }

        return $out;
    }

    /**
     * Everything for the Overview: the controls above plus the account's own
     * setup (risk profile, an active strategy, the broker connection) and
     * whether the active strategies' markets are open.
     *
     * @return list<array{code: string, message: string}>
     */
    public function forAccount(User $user, TradingAccount $account, ?TradingStatus $status = null): array
    {
        $account->loadMissing('connection');
        $out = $this->controls($user, $account, $status);
        if ($account->risk_profile_id === null) {
            $out[] = self::item('risk_profile_missing', 'Risk profile missing — choose one in Settings → Accounts.');
        }
        $symbols = StrategyAssignment::query()->where('account_id', $account->id)->where('status', AssignmentStatus::Enabled)
            ->distinct()->orderBy('symbol')->pluck('symbol')->all();
        if ($symbols === []) {
            $out[] = self::item('no_active_strategy', 'No strategy is active on this account.');
        }
        $connection = $account->getRelationValue('connection');
        if ($connection !== null && $connection->status !== ConnectionStatus::Connected) {
            $out[] = self::item('broker_disconnected', 'The broker connection is '.strtolower($connection->status->value).'.');
        }

        return [...$out, ...$this->marketClosed($account, $symbols)];
    }

    /**
     * One `market_closed` blocker per symbol whose market is closed right now,
     * e.g. "EURUSD market is closed until Sunday 21:00 UTC." (forex weekend).
     * Synthetic indices trade around the clock and never block.
     *
     * @param  iterable<string>  $symbols
     * @return list<array{code: string, message: string}>
     */
    public function marketClosed(TradingAccount $account, iterable $symbols): array
    {
        $out = [];
        foreach ($symbols as $symbol) {
            $closed = $this->hours->closed($account, $symbol);
            if ($closed === null) {
                continue;
            }
            $until = $closed['reopens_at']?->format('l H:i').' UTC';
            $out[] = self::item('market_closed', match (true) {
                $closed['reopens_at'] === null => "{$symbol} market is closed right now (as reported by the broker).",
                $closed['simulated'] => "{$symbol} market is closed in the Paper simulation until {$until} (simulated time).",
                default => "{$symbol} market is closed until {$until}.",
            });
        }

        return $out;
    }

    /** @return array{code: string, message: string} */
    private static function item(string $code, string $message): array
    {
        return ['code' => $code, 'message' => $message];
    }
}
