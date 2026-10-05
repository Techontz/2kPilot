<?php

namespace App\Policies;

use App\Policies\Concerns\OwnerWrites;

class BrokerConnectionPolicy
{
    use OwnerWrites;
}
