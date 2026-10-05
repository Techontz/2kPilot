<?php

namespace App\Models;

use App\Enums\TradingMode;

/** The single row (id = 1) holding the kill switch, operating mode and engine heartbeat. */
class SystemState extends BaseModel
{
    protected $table = 'system_state';

    public $incrementing = false;

    const CREATED_AT = null;

    protected function casts(): array
    {
        return [
            'trading_mode' => TradingMode::class,
            'kill_switch_engaged' => 'boolean',
            'kill_switch_changed_at' => 'datetime',
            'mode_changed_at' => 'datetime',
            'engine_lease_until' => 'datetime',
            'engine_heartbeat_at' => 'datetime',
            'engine_degraded' => 'boolean',
        ];
    }

    public static function current(): self
    {
        return static::query()->findOrFail(1);
    }
}
