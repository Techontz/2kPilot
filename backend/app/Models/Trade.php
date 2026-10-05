<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** A position from open to close — the unit of the journal and analytics. */
class Trade extends BaseModel
{
    use HasUuids;

    protected function casts(): array
    {
        return [
            'entry_time' => 'datetime',
            'exit_time' => 'datetime',
            'is_simulated' => 'boolean',
        ];
    }

    public function account(): BelongsTo
    {
        return $this->belongsTo(TradingAccount::class, 'account_id');
    }

    public function signal(): BelongsTo
    {
        return $this->belongsTo(Signal::class);
    }

    public function version(): BelongsTo
    {
        return $this->belongsTo(StrategyVersion::class, 'strategy_version_id');
    }
}
