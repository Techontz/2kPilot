<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Stored candle series used by backtests and paper "replay" accounts.
 * SYNTHETIC datasets are generated test data and are labelled everywhere.
 * A dataset belongs to the user who created it; user_id NULL = shared with
 * every user (read-only for non-admins).
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('datasets', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('user_id')->nullable()->constrained('users')->cascadeOnDelete();
            $table->string('symbol', 20);          // canonical, e.g. EURUSD
            $table->string('timeframe', 8);        // M1 … D1
            $table->string('source', 16);          // broker | csv | synthetic
            $table->string('source_ref', 120)->default(''); // connection id, file name or seed
            $table->string('description', 300)->default('');
            $table->dateTime('first_bar', 6)->nullable();
            $table->dateTime('last_bar', 6)->nullable();
            $table->unsignedInteger('bar_count')->default(0);
            $table->unsignedInteger('gap_count')->default(0);
            $table->string('checksum', 64)->default('');
            $table->utcTimestamps();

            $table->unique(['user_id', 'source', 'source_ref', 'symbol', 'timeframe'], 'uq_datasets_key');
        });
        DB::statement("ALTER TABLE datasets ADD CONSTRAINT ck_datasets_source CHECK (source IN ('broker','csv','synthetic'))");
        DB::statement("ALTER TABLE datasets ADD CONSTRAINT ck_datasets_timeframe CHECK (timeframe IN ('M1','M5','M15','M30','H1','H4','D1'))");

        Schema::create('candles', function (Blueprint $table) {
            $table->foreignUuid('dataset_id')->constrained('datasets')->cascadeOnDelete();
            $table->dateTime('time', 6);           // bar open time, UTC
            $table->decimal('open', 24, 10);
            $table->decimal('high', 24, 10);
            $table->decimal('low', 24, 10);
            $table->decimal('close', 24, 10);
            $table->unsignedBigInteger('tick_volume')->default(0);
            $table->integer('spread_points')->nullable();

            $table->primary(['dataset_id', 'time']);
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('candles');
        Schema::dropIfExists('datasets');
    }
};
