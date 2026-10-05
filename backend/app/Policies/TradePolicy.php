<?php

namespace App\Policies;

use App\Policies\Concerns\OwnerWrites;

class TradePolicy
{
    use OwnerWrites;
}
