<?php

namespace App\Models;

use App\Models\Concerns\BelongsToAccount;

/** The journal: one row per lifecycle step, under one correlation id. */
class TradeEvent extends BaseModel
{
    use BelongsToAccount;

    public $timestamps = false;

    protected function casts(): array
    {
        return ['occurred_at' => 'datetime', 'data' => 'array'];
    }
}
