<?php

namespace App\Models;

use App\Models\Concerns\BelongsToAccount;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * A trade intention (strategy or manual) and the risk engine's decision.
 * stop_loss is NULL for Rise/Fall contracts (the stake is the most they lose).
 */
class Signal extends BaseModel
{
    use BelongsToAccount, HasUuids;

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
