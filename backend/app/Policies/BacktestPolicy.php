<?php

namespace App\Policies;

use App\Policies\Concerns\OwnerWrites;

class BacktestPolicy
{
    use OwnerWrites;
}
