<?php

namespace App\Models;

/** Why a closed bar did — or did not — produce a signal. */
class StrategyEvaluation extends BaseModel
{
    const UPDATED_AT = null;

    protected function casts(): array
    {
        return ['bar_time' => 'datetime', 'checks' => 'array'];
    }
}
