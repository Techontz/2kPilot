<?php

namespace App\Policies;

use App\Policies\Concerns\OwnerWrites;

class DatasetPolicy
{
    use OwnerWrites;
}
