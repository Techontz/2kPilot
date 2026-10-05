<?php

namespace App\Models;

/** Balance / equity history — the source of equity curves and drawdown. */
class AccountSnapshot extends BaseModel
{
    public $timestamps = false;

    protected function casts(): array
    {
        return ['taken_at' => 'datetime'];
    }
}
