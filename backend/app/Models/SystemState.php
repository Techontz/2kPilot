<?php

namespace App\Models;

/**
 * The single row (id = 1) holding the PLATFORM HALT (columns kill_switch_*,
 * admin only — stops every user's trading) and the engine lease/heartbeat.
 * Each user's own STOP switch and mode live in user_trading_states.
 */
class SystemState extends BaseModel
{
    protected $table = 'system_state';

    public $incrementing = false;

    const CREATED_AT = null;

    protected function casts(): array
    {
        return [
            'kill_switch_engaged' => 'boolean',
            'kill_switch_changed_at' => 'datetime',
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
