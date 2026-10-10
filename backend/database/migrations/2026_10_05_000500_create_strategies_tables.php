<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

/**
 * Strategies and their immutable parameter versions. Signals, trades and
 * backtests always reference the exact version that produced them.
 *
 * user_id NULL = a built-in template: visible to everyone, changed only by
 * admins. Rule-based templates are seeded by the next migration (stable
 * `slug`); advanced code strategies (trend_pullback) are registered by the
 * trading engine on start-up. Users copy a template to get their own.
 *
 * key = implementation ("rules" for every builder / template / AI strategy,
 * whose versions' `parameters` ARE the rule set). source says how a user's
 * strategy was made. A strategy with trades or backtests is archived (not
 * deleted) so history keeps pointing at its exact versions.
 */
return new class extends Migration
{
    public function up(): void
    {
        Schema::create('strategies', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('user_id')->nullable()->constrained('users')->cascadeOnDelete();
            $table->string('key', 60);             // implementation id: "rules", "trend_pullback"
            $table->string('name', 120);
            $table->text('description');
            $table->string('slug', 80)->nullable()->unique('uq_strategies_slug'); // built-in templates only
            $table->string('source', 16)->default('builder'); // template | builder | ai | import | copy
            $table->string('summary', 300)->default('');
            $table->json('details')->nullable();   // how_it_works, struggles, suggested_*, difficulty, disclaimer
            $table->foreignUuid('copied_from_id')->nullable()->constrained('strategies')->nullOnDelete();
            $table->dateTime('archived_at', 6)->nullable();
            $table->utcTimestamps();

            $table->unique(['user_id', 'name'], 'uq_strategies_user_name');
        });
        DB::statement("ALTER TABLE strategies ADD CONSTRAINT ck_strategies_source CHECK (source IN ('template','builder','ai','import','copy'))");

        Schema::create('strategy_versions', function (Blueprint $table) {
            $table->uuid('id')->primary();
            $table->foreignUuid('strategy_id')->constrained('strategies')->cascadeOnDelete();
            $table->unsignedInteger('version');
            $table->string('code_version', 20);    // implementation semver
            $table->json('parameters');
            $table->text('rules_text')->nullable(); // plain-English summary of a rule set (engine to_text)
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
