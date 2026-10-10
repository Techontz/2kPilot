<?php

namespace App\Models;

use App\Models\Concerns\BelongsToAccount;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** Every instruction sent (or about to be sent) to a broker. Written only by the engine. */
class Order extends BaseModel
{
    use BelongsToAccount, HasUuids;

    protected function casts(): array
    {
        return [
            'is_simulated' => 'boolean',
            'multiplier' => 'integer',
            'duration' => 'integer',
            'expires_at' => 'datetime',
            'submitted_at' => 'datetime',
            'filled_at' => 'datetime',
            'last_reconciled_at' => 'datetime',
        ];
    }

    public function account(): BelongsTo
    {
        return $this->belongsTo(TradingAccount::class, 'account_id');
    }
}
