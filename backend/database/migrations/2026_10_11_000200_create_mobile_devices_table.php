<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * Phones registered for push notifications by the 2kPilot mobile app
 * (POST /api/mobile/devices). One row per Firebase Cloud Messaging token.
 *
 *  - fcm_token can be up to 4096 characters, too long for a unique index, so
 *    uniqueness is on fcm_token_hash (its SHA-256).
 *  - personal_access_token_id: the mobile sign-in it was registered with;
 *    signing that device out deletes the row (the app code does it, the FK
 *    only clears the link if a token disappears another way).
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('mobile_devices', function (Blueprint $table) {
            $table->id();
            $table->foreignUuid('user_id')->constrained('users')->cascadeOnDelete();
            $table->foreignId('personal_access_token_id')->nullable()->constrained('personal_access_tokens')->nullOnDelete();
            $table->text('fcm_token');
            $table->char('fcm_token_hash', 64)->unique();
            $table->string('platform', 10); // android | ios
            $table->string('app_version', 40)->nullable();
            $table->dateTime('last_seen_at', 6)->nullable();
            $table->utcTimestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('mobile_devices');
    }
};
