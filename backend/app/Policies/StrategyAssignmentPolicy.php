<?php

namespace App\Policies;

use App\Models\StrategyAssignment;
use App\Policies\Concerns\OwnsRecords;
use Illuminate\Database\Eloquent\Model;

/** An assignment belongs to the owner of its account. */
class StrategyAssignmentPolicy
{
    use OwnsRecords;

    /** @param  StrategyAssignment  $model */
    protected function ownerOf(Model $model): ?string
    {
        return $model->ownerId();
    }
}
