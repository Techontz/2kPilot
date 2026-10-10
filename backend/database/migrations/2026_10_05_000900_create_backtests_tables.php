<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Reproducible backtests: configuration, data identity (checksum) and results.
 * Runs are executed by the trading engine through a Laravel queue job.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('backtests', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('user_id')->constrained('users')->cascadeOnDelete();
            $table->foreignUuid('parent_id')->nullable()->constrained('backtests')->cascadeOnDelete();
            $table->string('kind', 24);
            $table->string('name', 200)->default('');
            $table->string('status', 16)->default('QUEUED');
            $table->string('strategy_key', 60);
            $table->foreignUuid('strategy_version_id')->nullable()->constrained('strategy_versions')->nullOnDelete();
            $table->string('code_version', 20);
            $table->json('parameters');
            $table->string('symbol', 20);
            $table->string('timeframe', 8);
            $table->foreignUuid('dataset_id')->nullable()->constrained('datasets')->nullOnDelete();
            $table->string('data_source', 16);
            $table->string('data_checksum', 64)->default('');
            $table->dateTime('start', 6);
            $table->dateTime('end', 6);
            $table->decimal('initial_capital', 20, 6);
            $table->string('account_currency', 8);
            $table->json('risk_settings');
            $table->json('costs');                 // spread, commission, slippage, swap
            $table->json('config');                // split / walk-forward / grid settings, contract, payout_ratio, commission_pct
            $table->unsignedInteger('progress')->default(0);
            $table->text('error')->nullable();
            $table->json('metrics')->nullable();
            $table->json('report')->nullable();    // curves, monthly results, warnings
            $table->dateTime('created_at', 6)->useCurrent();
            $table->dateTime('started_at', 6)->nullable();
            $table->dateTime('finished_at', 6)->nullable();

            $table->index(['user_id', 'created_at'], 'ix_backtests_user_created');
        });
        DB::statement("ALTER TABLE backtests ADD CONSTRAINT ck_backtests_status CHECK (status IN ('QUEUED','RUNNING','COMPLETED','FAILED'))");

        Schema::create('backtest_trades', function (Blueprint $table) {
            $table->id();
            $table->foreignUuid('backtest_id')->constrained('backtests')->cascadeOnDelete();
            $table->string('symbol', 20);
            $table->string('side', 8);
            $table->dateTime('signal_time', 6);
            $table->dateTime('entry_time', 6);
            $table->decimal('entry_price', 24, 10);
            $table->dateTime('exit_time', 6);
            $table->decimal('exit_price', 24, 10);
            $table->string('exit_reason', 16);
            $table->decimal('volume', 16, 4);
            $table->decimal('stop_loss', 24, 10)->nullable();     // NULL for Rise/Fall contracts
            $table->decimal('take_profit', 24, 10)->nullable();
            $table->decimal('risk_amount', 20, 6);
            $table->string('contract_type', 8)->nullable();        // NULL = SPOT
            $table->decimal('stake', 20, 6)->nullable();
            $table->decimal('payout', 20, 6)->nullable();          // Rise/Fall: stake × (1 + payout ratio), an ESTIMATE
            $table->string('outcome', 10)->nullable();             // WON | LOST | SOLD
            $table->decimal('gross_pnl', 20, 6);
            $table->decimal('costs', 20, 6);
            $table->decimal('net_pnl', 20, 6);
            $table->decimal('r_multiple', 24, 10);
            $table->string('session', 20);
            $table->json('reasons');

            $table->index(['backtest_id', 'entry_time'], 'ix_backtest_trades_backtest');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('backtest_trades');
        Schema::dropIfExists('backtests');
    }
};
