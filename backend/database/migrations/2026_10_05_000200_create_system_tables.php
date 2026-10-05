<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Global trading controls (a single row) and operator settings.
 *
 * The kill switch starts ENGAGED: a fresh install cannot trade until someone
 * deliberately presses "Resume trading".
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('system_state', function (Blueprint $table) {
            $table->smallInteger('id')->primary();
            $table->string('trading_mode', 16)->default('DEMO'); // BACKTEST | DEMO | LIVE
            $table->boolean('kill_switch_engaged')->default(true);
            $table->text('kill_switch_reason')->nullable();
            $table->dateTime('kill_switch_changed_at', 6)->nullable();
            $table->foreignUuid('kill_switch_changed_by')->nullable()->constrained('users')->nullOnDelete();
            $table->dateTime('mode_changed_at', 6)->nullable();
            $table->foreignUuid('mode_changed_by')->nullable()->constrained('users')->nullOnDelete();
            // Trading-engine leadership lease: only one engine process may trade.
            $table->string('engine_owner', 100)->nullable();
            $table->dateTime('engine_lease_until', 6)->nullable();
            $table->dateTime('engine_heartbeat_at', 6)->nullable();
            $table->string('engine_detail', 500)->nullable();
            $table->boolean('engine_degraded')->default(false);
            $table->dateTime('updated_at', 6)->useCurrent()->useCurrentOnUpdate();
        });
        DB::statement('ALTER TABLE system_state ADD CONSTRAINT ck_system_state_singleton CHECK (id = 1)');
        DB::statement("ALTER TABLE system_state ADD CONSTRAINT ck_system_state_mode CHECK (trading_mode IN ('BACKTEST','DEMO','LIVE'))");
        DB::table('system_state')->insert([
            'id' => 1,
            'trading_mode' => 'DEMO',
            'kill_switch_engaged' => true,
            'kill_switch_reason' => 'Fresh install: trading starts stopped.',
        ]);

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
        Schema::dropIfExists('system_state');
    }
};
