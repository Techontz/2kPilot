<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

/**
 * Strategies and their immutable parameter versions. Signals, trades and
 * backtests always reference the exact version that produced them.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('strategies', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->string('key', 60);             // implementation id, e.g. "trend_pullback"
            $table->string('name', 120)->unique();
            $table->text('description');
            $table->utcTimestamps();
        });

        Schema::create('strategy_versions', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('strategy_id')->constrained('strategies')->cascadeOnDelete();
            $table->unsignedInteger('version');
            $table->string('code_version', 20);    // implementation semver
            $table->json('parameters');
            $table->string('notes', 500)->default('');
            $table->dateTime('created_at', 6)->useCurrent();
            $table->foreignUuid('created_by')->nullable()->constrained('users')->nullOnDelete();

            $table->unique(['strategy_id', 'version'], 'uq_strategy_versions_ver');
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('strategy_versions');
        Schema::dropIfExists('strategies');
    }
};
