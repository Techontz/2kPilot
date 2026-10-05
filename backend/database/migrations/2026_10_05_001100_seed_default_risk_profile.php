<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;

/**
 * The conservative default risk profile, so a new account can be protected
 * from the first minute. Values mirror trading-engine RiskLimits defaults.
 */
return new class extends Migration
{
    public function up(): void
    {
        DB::table('risk_profiles')->insert([
            'id' => (string) Str::uuid7(),
            'name' => 'Conservative (default)',
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
            'max_trades_per_day' => 5,
            'max_spread_pips' => '2.5',
            'max_slippage_pips' => '1.5',
            'min_stop_pips' => '8',
            'max_stop_pips' => '150',
            'min_reward_risk' => '1.5',
            'allowed_sessions' => json_encode(['LONDON', 'OVERLAP', 'NEW_YORK']),
            'trading_hours_start' => null,
            'trading_hours_end' => null,
            'cooldown_after_losses' => 3,
            'cooldown_minutes' => 240,
            'max_data_age_seconds' => 120,
        ]);
    }

    public function down(): void
    {
        DB::table('risk_profiles')->where('name', 'Conservative (default)')->delete();
    }
};
