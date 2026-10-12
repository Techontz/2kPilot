<?php

namespace App\Models;

use App\Models\Concerns\BelongsToUser;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Database\Eloquent\Relations\HasOne;

/**
 * A strategy. user_id NULL = built-in template (shared, read-only for non-admins).
 *
 * key "rules" = a rule set built without code (template, builder, AI draft,
 * import); its versions' parameters ARE the rule set. Archived strategies
 * (archived_at set) are hidden from lists but keep their history.
 *
 * entries_disabled_* = an administrator's emergency stop for this strategy: the
 * engine refuses NEW entries from it (and from users' copies of it) for
 * everyone, with the reason. It never closes positions.
 */
class Strategy extends BaseModel
{
    use BelongsToUser, HasUuids;

    public const RULES = 'rules';

    public const SOURCES = ['template', 'builder', 'ai', 'import', 'copy'];

    protected function casts(): array
    {
        return ['details' => 'array', 'archived_at' => 'datetime', 'entries_disabled_at' => 'datetime'];
    }

    public function versions(): HasMany
    {
        return $this->hasMany(StrategyVersion::class)->orderBy('version');
    }

    public function latestVersion(): HasOne
    {
        return $this->hasOne(StrategyVersion::class)->ofMany('version', 'max');
    }

    public function assignments(): HasMany
    {
        return $this->hasMany(StrategyAssignment::class);
    }

    public function copiedFrom(): BelongsTo
    {
        return $this->belongsTo(self::class, 'copied_from_id');
    }

    public function scopeActive(Builder $query): void
    {
        $query->whereNull($this->qualifyColumn('archived_at'));
    }

    /** An administrator's emergency stop: no new entries from this strategy (or its copies). */
    public function entriesDisabled(): bool
    {
        return $this->entries_disabled_at !== null;
    }

    public function isRules(): bool
    {
        return $this->key === self::RULES;
    }
}
