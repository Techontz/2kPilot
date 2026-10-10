<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * In-app notifications written by the trading engine and by Laravel
 * (e.g. the scheduler's engine watchdog).
 *
 * user_id is the recipient (the account owner for account events). NULL =
 * a platform notification (engine offline, platform halt…) shown to admins.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('notifications', function (Blueprint $table) {
            $table->id();
            $table->foreignUuid('user_id')->nullable()->constrained('users')->cascadeOnDelete();
            $table->string('type', 40);            // e.g. "broker.disconnected"
            $table->string('severity', 16);        // info | success | warning | critical
            $table->string('title', 200);
            $table->string('message', 1000);
            $table->foreignUuid('account_id')->nullable()->constrained('trading_accounts')->cascadeOnDelete();
            $table->json('data');
            $table->dateTime('created_at', 6)->useCurrent();
            $table->dateTime('read_at', 6)->nullable();

            $table->index(['user_id', 'created_at'], 'ix_notifications_user_created');
            $table->index(['user_id', 'read_at'], 'ix_notifications_user_read');
        });
        DB::statement("ALTER TABLE notifications ADD CONSTRAINT ck_notifications_severity CHECK (severity IN ('info','success','warning','critical'))");
    }

    public function down(): void
    {
        Schema::dropIfExists('notifications');
    }
};
