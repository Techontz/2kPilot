<?php

namespace App\Models;

/** The journal: one row per lifecycle step, under one correlation id. */
class TradeEvent extends BaseModel
{
    public $timestamps = false;

    protected function casts(): array
    {
        return ['occurred_at' => 'datetime', 'data' => 'array'];
    }
}
