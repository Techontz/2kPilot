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
            $table->utcTimestamps();

            $table->unique(['account_id', 'strategy_id', 'symbol'], 'uq_assignments_target');
        });
        DB::statement("ALTER TABLE strategy_assignments ADD CONSTRAINT ck_strategy_assignments_status CHECK (status IN ('ENABLED','PAUSED'))");

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
