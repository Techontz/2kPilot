<?php

namespace App\Models;

use App\Enums\TradingMode;
use App\Models\Concerns\BelongsToUser;

/**
 * One user's trading controls: their own STOP switch and operating mode.
 * The engine reads this row on every tick for each of the user's accounts.
 */
class UserTradingState extends BaseModel
{
    use BelongsToUser;

    protected $primaryKey = 'user_id';

    protected $keyType = 'string';

    public $incrementing = false;

    protected function casts(): array
    {
        return [
            'trading_mode' => TradingMode::class,
            'kill_switch_engaged' => 'boolean',
            'kill_switch_changed_at' => 'datetime',
            'mode_changed_at' => 'datetime',
            'live_authorized_at' => 'datetime',
            'live_authorized_limits' => 'array',
            'live_revoked_at' => 'datetime',
        ];
    }
}
