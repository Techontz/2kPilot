<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Strategy assignments (one strategy version on one symbol of one account,
 * PAUSED by default) and the per-bar evaluations that explain every decision.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('strategy_assignments', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('strategy_id')->constrained('strategies')->cascadeOnDelete();
            $table->foreignUuid('strategy_version_id')->constrained('strategy_versions')->restrictOnDelete();
            $table->foreignUuid('account_id')->constrained('trading_accounts')->cascadeOnDelete();
            $table->string('symbol', 40);                  // broker symbol name
            $table->string('status', 16)->default('PAUSED');
            $table->string('status_reason', 300)->nullable();
            $table->dateTime('last_bar_evaluated', 6)->nullable();
            $table->dateTime('last_signal_at', 6)->nullable();
            // Contract specification: how the strategy's BUY/SELL signals are traded.
            //  SPOT       lots + stop loss/take profit prices (Paper only)
            //  RISE_FALL  BUY → CALL (CALLE with allow_equals), SELL → PUT (PUTE)
            //  MULTIPLIER BUY → MULTUP, SELL → MULTDOWN
            $table->string('contract_family', 16)->default('SPOT');
            $table->unsignedInteger('duration')->nullable();               // RISE_FALL
            $table->string('duration_unit', 1)->nullable();                // t | s | m | h | d
            $table->boolean('allow_equals')->default(false);               // RISE_FALL: equal spots win
            $table->decimal('stake', 12, 2)->nullable();                   // NULL = the risk profile's stake
            $table->unsignedInteger('multiplier')->nullable();             // MULTIPLIER
            $table->decimal('take_profit_amount', 14, 2)->nullable();      // MULTIPLIER, money
            $table->decimal('stop_loss_amount', 14, 2)->nullable();        // MULTIPLIER, money
            $table->utcTimestamps();

            $table->unique(['account_id', 'strategy_id', 'symbol'], 'uq_assignments_target');
        });
        DB::statement("ALTER TABLE strategy_assignments ADD CONSTRAINT ck_strategy_assignments_status CHECK (status IN ('ENABLED','PAUSED'))");
        DB::statement("ALTER TABLE strategy_assignments ADD CONSTRAINT ck_strategy_assignments_contract CHECK (contract_family IN ('RISE_FALL','MULTIPLIER','SPOT'))");
        DB::statement("ALTER TABLE strategy_assignments ADD CONSTRAINT ck_strategy_assignments_unit CHECK (duration_unit IS NULL OR duration_unit IN ('t','s','m','h','d'))");
        DB::statement("ALTER TABLE strategy_assignments ADD CONSTRAINT ck_strategy_assignments_rise_fall CHECK (contract_family <> 'RISE_FALL' OR (duration > 0 AND duration_unit IS NOT NULL))");
        DB::statement("ALTER TABLE strategy_assignments ADD CONSTRAINT ck_strategy_assignments_multiplier CHECK (contract_family <> 'MULTIPLIER' OR multiplier > 0)");

        Schema::create('strategy_evaluations', function (Blueprint $table) {
            $table->id();
            $table->foreignUuid('assignment_id')->constrained('strategy_assignments')->cascadeOnDelete();
            $table->dateTime('bar_time', 6);
            $table->string('outcome', 20);                 // SIGNAL | NO_SETUP | INSUFFICIENT_DATA
            $table->string('summary', 300);
            $table->json('checks');
            $table->dateTime('created_at', 6)->useCurrent();

            $table->index(['assignment_id', 'bar_time'], 'ix_strategy_evaluations_assignment_bar');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('strategy_evaluations');
        Schema::dropIfExists('strategy_assignments');
    }
};
