<?php

namespace App\Models;

use App\Enums\AccountEnvironment;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class TradingAccount extends BaseModel
{
    use HasUuids;

    protected function casts(): array
    {
        return [
            'environment' => AccountEnvironment::class,
            'trading_enabled' => 'boolean',
            'capabilities' => 'array',
            'synced_at' => 'datetime',
        ];
    }

    public function connection(): BelongsTo
    {
        return $this->belongsTo(BrokerConnection::class, 'connection_id');
    }

    public function riskProfile(): BelongsTo
    {
        return $this->belongsTo(RiskProfile::class);
    }

    public function assignments(): HasMany
    {
        return $this->hasMany(StrategyAssignment::class, 'account_id');
    }

    public function trades(): HasMany
    {
        return $this->hasMany(Trade::class, 'account_id');
    }

    public function snapshots(): HasMany
    {
        return $this->hasMany(AccountSnapshot::class, 'account_id');
    }

    public function isPaper(): bool
    {
        return $this->environment === AccountEnvironment::Paper;
    }
}
