<?php

namespace App\Policies;

use App\Models\TradingAccount;
use App\Models\User;
use App\Policies\Concerns\OwnsRecords;

class TradingAccountPolicy
{
    use OwnsRecords;

    /**
     * Place manual tickets, close or modify positions, assign strategies on
     * this account. Only its owner — never an admin on someone else's account.
     */
    public function trade(User $user, TradingAccount $account): bool
    {
        return $user->is_active && $account->user_id === $user->id;
    }
}
