<?php

namespace App\Models;

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
