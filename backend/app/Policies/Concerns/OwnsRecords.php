<?php

namespace App\Policies\Concerns;

use App\Models\User;
use Illuminate\Database\Eloquent\Model;

/**
 * Ownership rules shared by every policy:
 *  - a user sees and changes only their own records;
 *  - shared rows (user_id NULL: built-in strategies, shared datasets) are
 *    readable by everyone and changed only by admins;
 *  - admins may READ any record, but change only their own (and shared ones);
 *  - ACTING with a record (running or copying a strategy, asking a broker
 *    through a connection) needs `use`: own or shared, never admin-read.
 *    Trading on an account is never extended to admins — see TradingAccountPolicy.
 */
trait OwnsRecords
{
    /** The owning user's id; NULL = shared. Override for rows owned through an account. */
    protected function ownerOf(Model $model): ?string
    {
        return $model->getAttribute('user_id');
    }

    protected function owns(User $user, Model $model): bool
    {
        return $this->ownerOf($model) === $user->id;
    }

    public function viewAny(User $user): bool
    {
        return $user->is_active;
    }

    public function view(User $user, Model $model): bool
    {
        return $user->is_active && ($this->owns($user, $model) || $this->ownerOf($model) === null || $user->isAdmin());
    }

    /** Act with the record (not just look at it): admins get no extra reach here. */
    public function use(User $user, Model $model): bool
    {
        return $user->is_active && ($this->owns($user, $model) || $this->ownerOf($model) === null);
    }

    public function create(User $user): bool
    {
        return $user->is_active;
    }

    public function update(User $user, Model $model): bool
    {
        return $user->is_active && ($this->owns($user, $model) || ($this->ownerOf($model) === null && $user->isAdmin()));
    }

    public function delete(User $user, Model $model): bool
    {
        return $this->update($user, $model);
    }
}
