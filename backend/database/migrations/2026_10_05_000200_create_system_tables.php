<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Platform-wide controls (a single row), per-user trading controls and
 * operator settings.
 *
 * - system_state: the engine leadership lease and heartbeat, and the
 *   PLATFORM HALT — an admin-only emergency stop for every user at once.
 * - user_trading_states: each user's own STOP switch and operating mode.
 *   A new user starts STOPPED in DEMO mode: nothing trades until the user
 *   deliberately presses "Resume trading".
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('system_state', function (Blueprint $table) {
            $table->smallInteger('id')->primary();
            // Platform halt (admins only): while engaged, no account of any user trades.
            $table->boolean('kill_switch_engaged')->default(false);
            $table->text('kill_switch_reason')->nullable();
            $table->dateTime('kill_switch_changed_at', 6)->nullable();
            $table->foreignUuid('kill_switch_changed_by')->nullable()->constrained('users')->nullOnDelete();
            // Trading-engine leadership lease: only one engine process may trade.
            $table->string('engine_owner', 100)->nullable();
            $table->dateTime('engine_lease_until', 6)->nullable();
            $table->dateTime('engine_heartbeat_at', 6)->nullable();
            $table->string('engine_detail', 500)->nullable();
            $table->boolean('engine_degraded')->default(false);
            $table->dateTime('updated_at', 6)->useCurrent()->useCurrentOnUpdate();
        });
        DB::statement('ALTER TABLE system_state ADD CONSTRAINT ck_system_state_singleton CHECK (id = 1)');
        DB::table('system_state')->insert(['id' => 1, 'kill_switch_engaged' => false]);

        Schema::create('user_trading_states', function (Blueprint $table) {
            $table->foreignUuid('user_id')->primary()->constrained('users')->cascadeOnDelete();
            $table->string('trading_mode', 16)->default('DEMO'); // DEMO | LIVE
            $table->boolean('kill_switch_engaged')->default(true); // a new user starts stopped
            $table->text('kill_switch_reason')->nullable();
            $table->dateTime('kill_switch_changed_at', 6)->nullable();
            $table->dateTime('mode_changed_at', 6)->nullable();
            // Set when the user switched to LIVE (MFA + password + typed phrase),
            // with a snapshot of the risk limits they saw at that moment.
            $table->dateTime('live_authorized_at', 6)->nullable();
            $table->json('live_authorized_limits')->nullable();
            // The one LIVE account (and its risk profile) that authorisation covers:
            // the engine trades a LIVE account only if both still match and the
            // profile was not edited after live_authorized_at. The foreign keys
            // (nullOnDelete) are added with trading_accounts, which is created later.
            $table->uuid('live_authorized_account_id')->nullable();
            $table->uuid('live_authorized_profile_id')->nullable();
            // Why real-money authorisation was last taken away (profile edited,
            // MFA turned off, …), shown to the user until they authorise again.
            $table->text('live_revoked_reason')->nullable();
            $table->dateTime('live_revoked_at', 6)->nullable();
            $table->utcTimestamps();
        });
        DB::statement("ALTER TABLE user_trading_states ADD CONSTRAINT ck_user_trading_states_mode CHECK (trading_mode IN ('DEMO','LIVE'))");

        Schema::create('system_settings', function (Blueprint $table) {
            $table->string('key', 100)->primary();
            $table->json('value');
            $table->dateTime('updated_at', 6)->useCurrent()->useCurrentOnUpdate();
            $table->foreignUuid('updated_by')->nullable()->constrained('users')->nullOnDelete();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('system_settings');
        Schema::dropIfExists('user_trading_states');
        Schema::dropIfExists('system_state');
    }
};
