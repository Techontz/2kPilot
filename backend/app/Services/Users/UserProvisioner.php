<?php

namespace App\Services\Users;

use App\Enums\TradingMode;
use App\Models\RiskProfile;
use App\Models\User;
use App\Models\UserTradingState;
use Illuminate\Support\Facades\DB;

/**
 * Everything a new user needs from the first minute, created in one place for
 * sign-up and `php artisan tp:user`:
 *  - a conservative "Beginner" risk profile, so a new account can be
 *    protected immediately (values mirror trading-engine RiskLimits defaults);
 *  - their trading state: DEMO mode, trading STOPPED until they resume it.
 */
class UserProvisioner
{
    public const BEGINNER_LIMITS = [
        'risk_per_trade_pct' => '0.5',
        'max_position_lots' => '1.0',
        'max_open_positions' => 3,
        'max_positions_per_symbol' => 1,
        'max_symbol_exposure_lots' => '1.0',
        'max_total_exposure_lots' => '3.0',
        'max_total_risk_pct' => '2.0',
        'max_daily_loss_pct' => '2.0',
        'max_weekly_loss_pct' => '4.0',
        'max_drawdown_pct' => '10.0',
        'max_trades_per_day' => 20,
        'max_spread_pips' => '2.5',
        'max_slippage_pips' => '1.5',
        'min_stop_pips' => '8',
        'max_stop_pips' => '150',
        'min_reward_risk' => '1.5',
        'allowed_sessions' => ['LONDON', 'OVERLAP', 'NEW_YORK'],
        'trading_hours_start' => null,
        'trading_hours_end' => null,
        'cooldown_after_losses' => 3,
        'cooldown_minutes' => 240,
        'max_data_age_seconds' => 120,
        // Deriv contracts (Rise/Fall, Multipliers): a small fixed stake.
        'stake_amount' => '1.00',
        'max_stake_amount' => '5.00',
        'max_daily_loss_amount' => null,
        'max_consecutive_losses' => 3,
        'daily_profit_target_amount' => null,
    ];

    public function provision(User $user): void
    {
        DB::transaction(function () use ($user) {
            RiskProfile::query()->firstOrCreate(
                ['user_id' => $user->id, 'name' => RiskProfile::DEFAULT_NAME],
                self::BEGINNER_LIMITS,
            );
            UserTradingState::query()->firstOrCreate(['user_id' => $user->id], [
                'trading_mode' => TradingMode::Demo,
                'kill_switch_engaged' => true,
                'kill_switch_reason' => 'New account: trading starts stopped.',
            ]);
        });
    }
}
