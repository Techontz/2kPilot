<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** An instrument as reported by a connection's broker. */
class BrokerSymbol extends BaseModel
{
    const CREATED_AT = null;

    protected function casts(): array
    {
        return ['trade_allowed' => 'boolean', 'market_open' => 'boolean'];
    }

    public function connection(): BelongsTo
    {
        return $this->belongsTo(BrokerConnection::class, 'connection_id');
    }
}
