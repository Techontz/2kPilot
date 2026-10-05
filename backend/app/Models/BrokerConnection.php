<?php

namespace App\Models;

use App\Enums\AccountEnvironment;
use App\Enums\ConnectionStatus;
use App\Enums\ConnectorType;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\HasMany;

/**
 * How 2kFX reaches a broker. `credentials_encrypted` holds AES-256-GCM
 * ciphertext and is hidden from every serialisation.
 */
class BrokerConnection extends BaseModel
{
    use HasUuids;

    protected $hidden = ['credentials_encrypted'];

    protected function casts(): array
    {
        return [
            'connector_type' => ConnectorType::class,
            'expected_environment' => AccountEnvironment::class,
            'status' => ConnectionStatus::class,
            'settings' => 'array',
            'is_enabled' => 'boolean',
            'last_connected_at' => 'datetime',
            'last_error_at' => 'datetime',
        ];
    }

    public function accounts(): HasMany
    {
        return $this->hasMany(TradingAccount::class, 'connection_id');
    }

    public function symbols(): HasMany
    {
        return $this->hasMany(BrokerSymbol::class, 'connection_id');
    }
}
