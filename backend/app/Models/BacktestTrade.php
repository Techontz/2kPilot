<?php

namespace App\Models;

/** One simulated trade. Contract trades carry contract_type, stake, payout (an estimate) and outcome. */
class BacktestTrade extends BaseModel
{
    public $timestamps = false;

    protected function casts(): array
    {
        return [
            'signal_time' => 'datetime',
            'entry_time' => 'datetime',
            'exit_time' => 'datetime',
            'reasons' => 'array',
        ];
    }
}
