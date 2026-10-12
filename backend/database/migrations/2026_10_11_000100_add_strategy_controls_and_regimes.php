<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * Additive columns only (deployed databases keep every row):
 *
 *  - strategies.entries_disabled_*: an administrator's emergency stop for one
 *    strategy. While set, the engine refuses NEW entries from it (and from
 *    users' copies of it) for everyone, with the reason. It never closes
 *    positions. Set/cleared through POST /api/admin/strategies/{id}/disable|enable.
 *  - risk_profiles.min_account_balance: optional; no new trades while the
 *    account balance is below it (NULL = off).
 *  - backtest_trades.regime: the market regime at entry (TREND_UP, TREND_DOWN,
 *    SIDEWAYS, HIGH_VOLATILITY, UNCERTAIN) for "results by regime".
 *
 * The built-in "Adaptive Trend & Momentum" strategy itself is registered by
 * the trading engine on start-up (idempotent, like Trend Pullback V1).
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::table('strategies', function (Blueprint $table) {
            $table->dateTime('entries_disabled_at', 6)->nullable()->after('archived_at');
            $table->string('entries_disabled_reason', 300)->nullable()->after('entries_disabled_at');
            $table->foreignUuid('entries_disabled_by')->nullable()->after('entries_disabled_reason')
                ->constrained('users')->nullOnDelete();
        });
        Schema::table('risk_profiles', function (Blueprint $table) {
            $table->decimal('min_account_balance', 14, 2)->nullable()->after('daily_profit_target_amount');
        });
        Schema::table('backtest_trades', function (Blueprint $table) {
            $table->string('regime', 20)->nullable()->after('session');
        });
    }

    public function down(): void
    {
        Schema::table('backtest_trades', function (Blueprint $table) {
            $table->dropColumn('regime');
        });
        Schema::table('risk_profiles', function (Blueprint $table) {
            $table->dropColumn('min_account_balance');
        });
        Schema::table('strategies', function (Blueprint $table) {
            $table->dropConstrainedForeignId('entries_disabled_by');
            $table->dropColumn(['entries_disabled_at', 'entries_disabled_reason']);
        });
    }
};
