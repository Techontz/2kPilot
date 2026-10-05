<?php

namespace App\Policies\Concerns;

use App\Models\User;

/**
 * Roles: an OWNER may view and change everything; a VIEWER may only view.
 * Every policy in this application follows that rule.
 */
trait OwnerWrites
{
    public function viewAny(User $user): bool
    {
        return $user->is_active;
    }

    public function view(User $user, mixed $model = null): bool
    {
        return $user->is_active;
    }

    public function create(User $user): bool
    {
        return $user->is_active && $user->isOwner();
    }

    public function update(User $user, mixed $model = null): bool
    {
        return $user->is_active && $user->isOwner();
    }

    public function delete(User $user, mixed $model = null): bool
    {
        return $user->is_active && $user->isOwner();
    }
}
