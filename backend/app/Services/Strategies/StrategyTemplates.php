<?php

namespace App\Services\Strategies;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use RuntimeException;

/**
 * The built-in rule-based templates (database/data/strategy_templates.json).
 *
 * Shared rows (user_id NULL), keyed by a stable `slug`, so syncing is
 * idempotent: an unchanged template is left alone; a template whose rules
 * changed gets a NEW version (old versions stay — signals, trades and
 * backtests point at them). The engine's test suite validates every
 * template in that file, and its `rules_text` against the engine's own.
 *
 * Templates are educational starting points, never claimed to be profitable.
 */
class StrategyTemplates
{
    public const KEY = 'rules';

    public static function path(): string
    {
        return database_path('data/strategy_templates.json');
    }

    /** @return list<array<string, mixed>> */
    public static function all(): array
    {
        $raw = file_get_contents(self::path());
        if ($raw === false) {
            throw new RuntimeException('database/data/strategy_templates.json is missing.');
        }
        $data = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);

        return $data['templates'];
    }

    /** Create or update every template. Returns how many rows changed. */
    public static function sync(): int
    {
        $codeVersion = (string) (json_decode((string) file_get_contents(self::path()), true)['code_version'] ?? '1.0.0');
        $changed = 0;
        foreach (self::all() as $t) {
            $now = now()->utc()->format('Y-m-d H:i:s.u');
            $row = [
                'key' => self::KEY,
                'name' => $t['name'],
                'description' => $t['summary'],
                'summary' => $t['summary'],
                'details' => json_encode($t['details'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
                'source' => 'template',
                'updated_at' => $now,
            ];
            $id = DB::table('strategies')->where('slug', $t['slug'])->value('id');
            if ($id === null) {
                $id = (string) Str::uuid();
                DB::table('strategies')->insert($row + ['id' => $id, 'slug' => $t['slug'], 'user_id' => null, 'created_at' => $now]);
                $changed++;
            } else {
                DB::table('strategies')->where('id', $id)->update($row);
            }
            $latest = DB::table('strategy_versions')->where('strategy_id', $id)->orderByDesc('version')->first();
            if ($latest !== null && json_decode($latest->parameters, true) == $t['rules']) {
                continue;
            }
            DB::table('strategy_versions')->insert([
                'id' => (string) Str::uuid(),
                'strategy_id' => $id,
                'version' => ($latest->version ?? 0) + 1,
                'code_version' => $codeVersion,
                'parameters' => json_encode($t['rules'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
                'rules_text' => $t['rules_text'],
                'notes' => $latest === null ? 'Template' : 'Template updated',
                'created_at' => $now,
                'created_by' => null,
            ]);
            $changed++;
        }

        return $changed;
    }

    /** The template slugs (used by the migration's rollback). */
    public static function slugs(): array
    {
        return array_column(self::all(), 'slug');
    }
}
