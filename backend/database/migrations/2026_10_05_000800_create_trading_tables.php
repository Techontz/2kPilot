<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * The trade lifecycle: signal → risk decision → order → trade (position) → journal.
 *
 * - signals: a trade intention from a strategy (source STRATEGY) or a person
 *   (source MANUAL), plus the risk engine's decision and every rule's result.
 * - orders: every instruction sent (or about to be sent) to a broker. The
 *   order row is written BEFORE anything is sent; client_order_id is the
 *   idempotency key used to reconcile uncertain outcomes.
 * - trades: a position from open to close — the unit of analytics.
 * - trade_events: the append-only journal under one correlation id.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('signals', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->string('source', 16)->default('STRATEGY');    // STRATEGY | MANUAL
            $table->foreignUuid('assignment_id')->nullable()->constrained('strategy_assignments')->nullOnDelete();
            $table->foreignUuid('strategy_version_id')->nullable()->constrained('strategy_versions')->restrictOnDelete();
            $table->foreignUuid('account_id')->constrained('trading_accounts')->cascadeOnDelete();
            $table->foreignUuid('created_by')->nullable()->constrained('users')->nullOnDelete();
            // Manual orders: one key per confirmed ticket, so a double-click
            // or a retried request can never open a second position.
            $table->string('idempotency_key', 64)->nullable()->unique();
            $table->string('symbol', 40);
            $table->string('side', 8);
            $table->string('timeframe', 8);
            $table->dateTime('bar_time', 6);
            $table->string('entry_type', 16);
            $table->decimal('entry_price', 24, 10);
            $table->decimal('stop_loss', 24, 10);
            $table->decimal('take_profit', 24, 10)->nullable();
            $table->json('reasons');
            $table->string('status', 16)->default('NEW');
            $table->json('risk_checks');
            $table->string('rejection_reason', 500)->nullable();
            $table->decimal('requested_volume', 16, 4)->nullable(); // manual orders only
            $table->decimal('volume', 16, 4)->nullable();
            $table->decimal('risk_amount', 20, 6)->nullable();
            $table->string('correlation_id', 64)->nullable();
            $table->dateTime('created_at', 6)->useCurrent();
            $table->dateTime('decided_at', 6)->nullable();

            // Duplicate-signal protection: one signal per assignment, bar and direction.
            $table->unique(['assignment_id', 'bar_time', 'side'], 'uq_signals_dedupe');
            $table->index(['account_id', 'created_at'], 'ix_signals_account_created');
        });
        DB::statement("ALTER TABLE signals ADD CONSTRAINT ck_signals_source CHECK (source IN ('STRATEGY','MANUAL'))");
        DB::statement("ALTER TABLE signals ADD CONSTRAINT ck_signals_side CHECK (side IN ('BUY','SELL'))");
        DB::statement("ALTER TABLE signals ADD CONSTRAINT ck_signals_status CHECK (status IN ('NEW','APPROVED','REJECTED','SKIPPED','EXECUTED','FAILED'))");
        DB::statement("ALTER TABLE signals ADD CONSTRAINT ck_signals_strategy CHECK (source = 'MANUAL' OR strategy_version_id IS NOT NULL)");

        Schema::create('trades', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('account_id')->constrained('trading_accounts')->cascadeOnDelete();
            $table->foreignUuid('signal_id')->nullable()->constrained('signals')->nullOnDelete();
            $table->foreignUuid('strategy_version_id')->nullable()->constrained('strategy_versions')->nullOnDelete();
            $table->string('symbol', 40);
            $table->string('side', 8);
            $table->string('status', 8)->default('OPEN');
            $table->decimal('volume', 16, 4);
            $table->decimal('requested_entry', 24, 10)->nullable();
            $table->decimal('entry_price', 24, 10);
            $table->dateTime('entry_time', 6);
            $table->decimal('stop_loss', 24, 10)->nullable();
            $table->decimal('take_profit', 24, 10)->nullable();
            $table->decimal('initial_stop_loss', 24, 10)->nullable();
            $table->decimal('risk_amount', 20, 6)->nullable();
            $table->decimal('spread_at_entry', 24, 10)->nullable();
            $table->decimal('slippage_pips', 24, 10)->nullable();
            $table->string('session', 20)->nullable();
            $table->string('broker_position_id', 64)->nullable();
            $table->decimal('exit_price', 24, 10)->nullable();
            $table->dateTime('exit_time', 6)->nullable();
            $table->string('exit_reason', 16)->nullable();
            $table->decimal('gross_pnl', 20, 6)->nullable();
            $table->decimal('commission', 20, 6)->default(0);
            $table->decimal('swap', 20, 6)->default(0);
            $table->decimal('net_pnl', 20, 6)->nullable();
            $table->decimal('unrealized_pnl', 20, 6)->nullable();
            $table->decimal('r_multiple', 24, 10)->nullable();
            $table->boolean('is_simulated')->default(false);
            $table->utcTimestamps();

            $table->index(['account_id', 'status'], 'ix_trades_account_status');
            $table->index(['account_id', 'exit_time'], 'ix_trades_account_exit');
            $table->unique(['account_id', 'broker_position_id'], 'uq_trades_broker_position');
        });
        DB::statement("ALTER TABLE trades ADD CONSTRAINT ck_trades_status CHECK (status IN ('OPEN','CLOSED'))");

        Schema::create('orders', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->string('client_order_id', 32)->unique();      // idempotency key sent to the broker
            $table->foreignUuid('account_id')->constrained('trading_accounts')->cascadeOnDelete();
            $table->foreignUuid('signal_id')->nullable()->constrained('signals')->nullOnDelete();
            $table->foreignUuid('trade_id')->nullable()->constrained('trades')->nullOnDelete();
            $table->string('purpose', 8);                          // ENTRY | EXIT
            $table->string('symbol', 40);
            $table->string('side', 8);
            $table->string('order_type', 16);                      // MARKET | LIMIT | STOP
            $table->decimal('volume', 16, 4);
            $table->decimal('filled_volume', 16, 4)->default(0);
            $table->decimal('requested_price', 24, 10)->nullable();
            $table->decimal('fill_price', 24, 10)->nullable();
            $table->decimal('stop_loss', 24, 10)->nullable();
            $table->decimal('take_profit', 24, 10)->nullable();
            $table->string('status', 20)->default('PENDING_SUBMIT');
            $table->string('broker_order_id', 64)->nullable();
            $table->string('broker_position_id', 64)->nullable();
            $table->string('broker_code', 64)->nullable();
            $table->string('broker_message', 500)->nullable();
            $table->unsignedInteger('attempts')->default(0);
            $table->boolean('is_simulated')->default(false);
            $table->dateTime('submitted_at', 6)->nullable();
            $table->dateTime('filled_at', 6)->nullable();
            $table->dateTime('last_reconciled_at', 6)->nullable();
            $table->utcTimestamps();

            $table->index(['account_id', 'created_at'], 'ix_orders_account_created');
            $table->index('status', 'ix_orders_status');
        });
        DB::statement("ALTER TABLE orders ADD CONSTRAINT ck_orders_status CHECK (status IN ('PENDING_SUBMIT','SUBMITTED','PENDING','FILLED','PARTIALLY_FILLED','CANCELLED','REJECTED','UNKNOWN','FAILED'))");

        Schema::create('trade_events', function (Blueprint $table) {
            $table->id();
            $table->dateTime('occurred_at', 6)->useCurrent();
            $table->foreignUuid('account_id')->nullable()->constrained('trading_accounts')->cascadeOnDelete();
            $table->foreignUuid('signal_id')->nullable()->constrained('signals')->nullOnDelete();
            $table->foreignUuid('order_id')->nullable()->constrained('orders')->nullOnDelete();
            $table->foreignUuid('trade_id')->nullable()->constrained('trades')->nullOnDelete();
            $table->string('event_type', 40);
            $table->string('message', 500);
            $table->json('data');
            $table->string('correlation_id', 64)->nullable();

            $table->index(['account_id', 'occurred_at'], 'ix_trade_events_account_time');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('trade_events');
        Schema::dropIfExists('orders');
        Schema::dropIfExists('trades');
        Schema::dropIfExists('signals');
    }
};
