<?php

namespace App\Models;

use App\Models\Concerns\BelongsToAccount;

/** Balance / equity history — the source of equity curves and drawdown. */
class AccountSnapshot extends BaseModel
{
    use BelongsToAccount;

    public $timestamps = false;

    protected function casts(): array
    {
        return ['taken_at' => 'datetime'];
    }
}
