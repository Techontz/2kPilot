<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** A trade intention (strategy or manual) and the risk engine's decision. */
class Signal extends BaseModel
{
    use HasUuids;

    const UPDATED_AT = null;

    protected function casts(): array
    {
        return [
            'bar_time' => 'datetime',
            'decided_at' => 'datetime',
            'reasons' => 'array',
            'risk_checks' => 'array',
        ];
    }

    public function account(): BelongsTo
    {
        return $this->belongsTo(TradingAccount::class, 'account_id');
    }

    public function version(): BelongsTo
    {
        return $this->belongsTo(StrategyVersion::class, 'strategy_version_id');
    }
}
