<?php

use App\Services\Strategies\StrategyTemplates;
use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;

/**
 * Seed the built-in rule-based templates (EMA crossover, RSI mean reversion,
 * trend filter, Bollinger reversion, MACD momentum, breakout) as shared,
 * read-only strategies. Idempotent by slug — see StrategyTemplates.
 */
return new class extends Migration
{
    public function up(): void
    {
        StrategyTemplates::sync();
    }

    public function down(): void
    {
        DB::table('strategies')->whereNull('user_id')->whereIn('slug', StrategyTemplates::slugs())->delete();
    }
};
