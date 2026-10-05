<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Append-only audit trail of security- and trading-relevant actions.
 * Database triggers refuse UPDATE and DELETE, so history cannot be rewritten.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('audit_logs', function (Blueprint $table) {
            $table->id();
            $table->dateTime('occurred_at', 6)->useCurrent();
            $table->foreignUuid('actor_user_id')->nullable()->constrained('users')->nullOnDelete();
            $table->string('actor_label', 320); // email, or "system"
            $table->string('action', 100);      // e.g. "trading.kill_switch.engaged"
            $table->string('outcome', 16);      // success | failure | denied
            $table->string('target_type', 60)->nullable();
            $table->string('target_id', 100)->nullable();
            $table->string('ip_address', 64)->nullable();
            $table->string('user_agent', 512)->nullable();
            $table->string('correlation_id', 64)->nullable();
            $table->json('details');            // masked before insert

            $table->index('occurred_at', 'ix_audit_logs_occurred_at');
            $table->index(['action', 'occurred_at'], 'ix_audit_logs_action_occurred_at');
        });
        DB::statement("ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_outcome CHECK (outcome IN ('success','failure','denied'))");
        DB::unprepared("CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'");
        DB::unprepared("CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'");
    }

    public function down(): void
    {
        DB::unprepared('DROP TRIGGER IF EXISTS audit_logs_no_update');
        DB::unprepared('DROP TRIGGER IF EXISTS audit_logs_no_delete');
        Schema::dropIfExists('audit_logs');
    }
};
