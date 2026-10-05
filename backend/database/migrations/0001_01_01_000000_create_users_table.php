<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Users and their login sessions.
 *
 * Accounts are created from the command line (`php artisan fx:user`), never
 * through public sign-up. MFA secrets and recovery codes are stored encrypted.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('users', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->string('name', 120);
            $table->string('email', 320)->unique();
            $table->string('password');
            $table->string('role', 16)->default('owner'); // owner | viewer
            $table->boolean('is_active')->default(true);
            $table->text('two_factor_secret')->nullable();
            $table->text('two_factor_recovery_codes')->nullable();
            $table->dateTime('two_factor_confirmed_at', 6)->nullable();
            $table->dateTime('last_login_at', 6)->nullable();
            $table->rememberToken();
            $table->utcTimestamps();
        });
        DB::statement("ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN ('owner','viewer'))");
        DB::statement('ALTER TABLE users ADD CONSTRAINT ck_users_email_lowercase CHECK (CAST(email AS BINARY) = CAST(LOWER(email) AS BINARY))');

        Schema::create('sessions', function (Blueprint $table) {
            $table->string('id')->primary();
            $table->foreignUuid('user_id')->nullable()->index();
            $table->string('ip_address', 45)->nullable();
            $table->text('user_agent')->nullable();
            $table->longText('payload');
            $table->integer('last_activity')->index();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('sessions');
        Schema::dropIfExists('users');
    }
};
