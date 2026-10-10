<?php

namespace App\Models\Concerns;

use App\Models\TradingAccount;
use App\Models\User;
use Illuminate\Database\Eloquent\Builder;

/**
 * A row that belongs to a trading account (orders, trades, signals, journal,
 * assignments, snapshots…) and so to the account's owner.
 */
trait BelongsToAccount
{
    public function scopeOwnedBy(Builder $query, User $user): void
    {
        $query->whereIn($this->qualifyColumn('account_id'), TradingAccount::query()->ownedBy($user)->select('id'));
    }

    public function ownerId(): ?string
    {
        return TradingAccount::query()->whereKey($this->account_id)->value('user_id');
    }
}
