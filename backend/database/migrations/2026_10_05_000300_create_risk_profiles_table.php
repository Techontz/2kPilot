<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Risk limits, assigned per trading account. Typed columns (not JSON) so every
 * limit is explicit. NULL means "this optional limit is off"; the stop-loss
 * requirement and the global gates (kill switch, live lock) cannot be disabled.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('risk_profiles', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->string('name', 120)->unique();
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
            $table->utcTimestamps();
        });
        DB::statement('ALTER TABLE risk_profiles ADD CONSTRAINT ck_risk_profiles_risk CHECK (risk_per_trade_pct > 0 AND risk_per_trade_pct <= 5)');
    }

    public function down(): void
    {
        Schema::dropIfExists('risk_profiles');
    }
};
