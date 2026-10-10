<?php

namespace App\Policies;

use App\Models\Trade;
use App\Policies\Concerns\OwnsRecords;
use Illuminate\Database\Eloquent\Model;

/** A trade (position) belongs to the owner of its account. */
class TradePolicy
{
    use OwnsRecords;

    /** @param  Trade  $model */
    protected function ownerOf(Model $model): ?string
    {
        return $model->ownerId();
    }
}
