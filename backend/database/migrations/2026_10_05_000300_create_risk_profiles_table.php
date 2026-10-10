<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Risk limits, assigned per trading account. Typed columns (not JSON) so every
 * limit is explicit. NULL means "this optional limit is off"; the stop-loss
 * requirement and the gates (kill switch, platform halt, live lock) cannot be
 * disabled. Each profile belongs to one user; every user gets a "Beginner"
 * profile at sign-up (App\Services\Users\UserProvisioner).
 *
 * Pip/lot limits apply to SPOT trading (Paper). Contract trading (Deriv
 * Rise/Fall and Multipliers) is sized by a fixed stake instead.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('risk_profiles', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('user_id')->constrained('users')->cascadeOnDelete();
            $table->string('name', 120);
            $table->decimal('risk_per_trade_pct', 6, 3);
            $table->decimal('max_position_lots', 12, 4)->nullable();
            $table->unsignedInteger('max_open_positions')->nullable();
            $table->unsignedInteger('max_positions_per_symbol')->nullable();
            $table->decimal('max_symbol_exposure_lots', 12, 4)->nullable();
            $table->decimal('max_total_exposure_lots', 12, 4)->nullable();
            $table->decimal('max_total_risk_pct', 6, 3)->nullable();
            $table->decimal('max_daily_loss_pct', 6, 3)->nullable();
            $table->decimal('max_weekly_loss_pct', 6, 3)->nullable();
            $table->decimal('max_drawdown_pct', 6, 3)->nullable();
            $table->unsignedInteger('max_trades_per_day')->nullable();
            $table->decimal('max_spread_pips', 8, 2)->nullable();
            $table->decimal('max_slippage_pips', 8, 2)->nullable();
            $table->decimal('min_stop_pips', 8, 2)->nullable();
            $table->decimal('max_stop_pips', 8, 2)->nullable();
            $table->decimal('min_reward_risk', 6, 2)->nullable();
            $table->json('allowed_sessions');               // e.g. ["LONDON","NEW_YORK"]; [] = any
            $table->string('trading_hours_start', 5)->nullable(); // "HH:MM" UTC
            $table->string('trading_hours_end', 5)->nullable();
            $table->unsignedInteger('cooldown_after_losses')->nullable();
            $table->unsignedInteger('cooldown_minutes')->nullable();
            $table->unsignedInteger('max_data_age_seconds')->default(120);
            // Stake-based limits for Deriv Options contracts (Rise/Fall, Multipliers),
            // in the account currency. The stake is the most a contract can lose.
            $table->decimal('stake_amount', 12, 2)->default(1.00);           // fixed stake per trade
            $table->decimal('max_stake_amount', 12, 2)->nullable();          // cap on any stake
            $table->decimal('max_daily_loss_amount', 14, 2)->nullable();     // money, besides the % limit
            $table->unsignedInteger('max_consecutive_losses')->nullable();   // halt for the UTC day
            $table->decimal('daily_profit_target_amount', 14, 2)->nullable(); // stop for the day once reached
            $table->utcTimestamps();

            $table->unique(['user_id', 'name'], 'uq_risk_profiles_user_name');
        });
        DB::statement('ALTER TABLE risk_profiles ADD CONSTRAINT ck_risk_profiles_risk CHECK (risk_per_trade_pct > 0 AND risk_per_trade_pct <= 5)');
        DB::statement('ALTER TABLE risk_profiles ADD CONSTRAINT ck_risk_profiles_stake CHECK (stake_amount > 0 AND (max_stake_amount IS NULL OR stake_amount <= max_stake_amount))');
    }

    public function down(): void
    {
        Schema::dropIfExists('risk_profiles');
    }
};
