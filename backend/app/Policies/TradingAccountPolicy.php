<?php

namespace App\Policies;

use App\Models\TradingAccount;
use App\Models\User;
use App\Policies\Concerns\OwnerWrites;

class TradingAccountPolicy
{
    use OwnerWrites;

    /** Place manual tickets, close or modify positions on this account. */
    public function trade(User $user, TradingAccount $account): bool
    {
        return $user->is_active && $user->isOwner();
    }
}
