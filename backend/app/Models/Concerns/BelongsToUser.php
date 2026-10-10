<?php

namespace App\Models\Concerns;

use App\Models\User;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * A row owned by one user (column `user_id`). Every listing of such rows goes
 * through `ownedBy()` (or `visibleTo()` where shared rows exist), so one user
 * never sees another user's records.
 */
trait BelongsToUser
{
    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
    }

    public function scopeOwnedBy(Builder $query, User $user): void
    {
        $query->where($this->qualifyColumn('user_id'), $user->id);
    }

    /** Own rows plus shared ones (user_id NULL: built-in strategies, shared datasets). */
    public function scopeVisibleTo(Builder $query, User $user): void
    {
        $query->where(fn (Builder $q) => $q->where($this->qualifyColumn('user_id'), $user->id)->orWhereNull($this->qualifyColumn('user_id')));
    }

    public function isShared(): bool
    {
        return $this->user_id === null;
    }
}
