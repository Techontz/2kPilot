<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Broker connections and the trading accounts reached through them.
 *
 * - Secrets live only in `credentials_encrypted` (AES-256-GCM, BROKER_CREDENTIALS_KEY)
 *   and are never returned by the API.
 * - An account's environment (PAPER / DEMO / LIVE) is what the BROKER reported,
 *   not what the user typed.
 * - New accounts are saved with trading disabled.
 * - A connection and its accounts belong to one user. `trading_accounts.user_id`
 *   repeats the connection's owner because nearly every query filters by it.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('broker_connections', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('user_id')->constrained('users')->cascadeOnDelete();
            $table->string('label', 120);
            $table->string('connector_type', 24);          // paper | deriv
            $table->string('expected_environment', 16);    // what the user selected
            $table->json('settings');                      // non-secret configuration
            $table->text('credentials_encrypted')->nullable();
            $table->string('status', 16)->default('DISCONNECTED');
            $table->string('status_detail', 500)->nullable();
            $table->boolean('is_enabled')->default(true);
            $table->dateTime('last_connected_at', 6)->nullable();
            $table->dateTime('last_error_at', 6)->nullable();
            $table->utcTimestamps();
        });
        DB::statement("ALTER TABLE broker_connections ADD CONSTRAINT ck_broker_connections_type CHECK (connector_type IN ('paper','deriv'))");
        DB::statement("ALTER TABLE broker_connections ADD CONSTRAINT ck_broker_connections_env CHECK (expected_environment IN ('PAPER','DEMO','LIVE'))");
        DB::statement("ALTER TABLE broker_connections ADD CONSTRAINT ck_broker_connections_status CHECK (status IN ('CONNECTED','DISCONNECTED','RECONNECTING','ERROR'))");

        Schema::create('trading_accounts', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('connection_id')->constrained('broker_connections')->cascadeOnDelete();
            $table->foreignUuid('user_id')->constrained('users')->cascadeOnDelete(); // = connection owner
            $table->string('broker_account_id', 64);
            $table->string('label', 120);
            $table->string('name', 200)->default('');
            $table->string('server', 200)->default('');
            $table->string('currency', 8);
            $table->string('environment', 16);             // broker-reported
            $table->unsignedInteger('leverage')->nullable();
            $table->boolean('trading_enabled')->default(false);
            $table->foreignUuid('risk_profile_id')->nullable()->constrained('risk_profiles')->nullOnDelete();
            $table->json('capabilities');                  // what this broker supports (see BrokerAdapter)
            $table->decimal('balance', 20, 6)->nullable();
            $table->decimal('equity', 20, 6)->nullable();
            $table->decimal('margin', 20, 6)->nullable();
            $table->decimal('free_margin', 20, 6)->nullable();
            $table->decimal('margin_level', 20, 6)->nullable();
            $table->dateTime('synced_at', 6)->nullable();
            $table->utcTimestamps();

            $table->unique(['connection_id', 'broker_account_id'], 'uq_trading_accounts_login');
        });
        DB::statement("ALTER TABLE trading_accounts ADD CONSTRAINT ck_trading_accounts_env CHECK (environment IN ('PAPER','DEMO','LIVE','UNKNOWN'))");

        // user_trading_states (created earlier) points at the LIVE-authorised account and profile.
        Schema::table('user_trading_states', function (Blueprint $table) {
            $table->foreign('live_authorized_account_id', 'fk_uts_live_account')->references('id')->on('trading_accounts')->nullOnDelete();
            $table->foreign('live_authorized_profile_id', 'fk_uts_live_profile')->references('id')->on('risk_profiles')->nullOnDelete();
        });

        Schema::create('account_snapshots', function (Blueprint $table) {
            $table->id();
            $table->foreignUuid('account_id')->constrained('trading_accounts')->cascadeOnDelete();
            $table->dateTime('taken_at', 6)->useCurrent();
            $table->decimal('balance', 20, 6);
            $table->decimal('equity', 20, 6);
            $table->decimal('margin', 20, 6)->nullable();
            $table->unsignedInteger('open_positions')->default(0);

            $table->index(['account_id', 'taken_at'], 'ix_account_snapshots_account_time');
        });

        Schema::create('broker_symbols', function (Blueprint $table) {
            $table->id();
            $table->foreignUuid('connection_id')->constrained('broker_connections')->cascadeOnDelete();
            $table->string('name', 40);
            $table->string('canonical', 20)->index();
            $table->string('description', 200)->default('');
            $table->string('category', 30)->default('other'); // forex | commodities | indices | crypto | synthetic | stocks | other
            $table->string('base_currency', 8);
            $table->string('quote_currency', 8);
            $table->unsignedInteger('digits');
            $table->decimal('point', 24, 10);
            $table->decimal('contract_size', 20, 6);
            $table->decimal('volume_min', 16, 4);
            $table->decimal('volume_max', 16, 4);
            $table->decimal('volume_step', 16, 4);
            $table->boolean('trade_allowed');
            $table->boolean('market_open')->nullable();     // as last reported by the broker
            $table->dateTime('updated_at', 6)->useCurrent()->useCurrentOnUpdate();

            $table->unique(['connection_id', 'name'], 'uq_broker_symbols_name');
        });

        Schema::create('paper_states', function (Blueprint $table) {
            $table->foreignUuid('connection_id')->primary()->constrained('broker_connections')->cascadeOnDelete();
            $table->json('state');
            $table->dateTime('updated_at', 6)->useCurrent()->useCurrentOnUpdate();
        });
    }

    public function down(): void
    {
        Schema::table('user_trading_states', function (Blueprint $table) {
            $table->dropForeign('fk_uts_live_account');
            $table->dropForeign('fk_uts_live_profile');
        });
        Schema::dropIfExists('paper_states');
        Schema::dropIfExists('broker_symbols');
        Schema::dropIfExists('account_snapshots');
        Schema::dropIfExists('trading_accounts');
        Schema::dropIfExists('broker_connections');
    }
};
