<?php

namespace App\Policies;

use App\Policies\Concerns\OwnerWrites;

class RiskProfilePolicy
{
    use OwnerWrites;
}
