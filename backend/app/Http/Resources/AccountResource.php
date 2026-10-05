<?php

namespace App\Http\Resources;

use App\Models\TradingAccount;
use Illuminate\Http\Request;
use Illuminate\Http\Resources\Json\JsonResource;

/**
 * A trading account as shown on the Brokers account card. Secrets never
 * appear here: the connection's encrypted credentials are hidden.
 *
 * @mixin TradingAccount
 */
class AccountResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        $connection = $this->connection;
        $active = $this->relationLoaded('assignments')
            ? $this->assignments->where('status.value', 'ENABLED')->map(fn ($a) => $a->strategy?->name.' · '.$a->symbol)->values()
            : [];

        return [
            'id' => $this->id,
            'label' => $this->label,
            'broker' => config("brokers.{$connection->connector_type->value}.name"),
            'connector_type' => $connection->connector_type->value,
            'connection_id' => $connection->id,
            'connection_status' => $connection->status->value,
            'connection_detail' => $connection->status_detail,
            'connection_enabled' => $connection->is_enabled,
            'last_connected_at' => $connection->last_connected_at?->toIso8601String(),
            'broker_account_id' => $this->broker_account_id,
            'name' => $this->name,
            'server' => $this->server,
            'environment' => $this->environment->value,
            'currency' => $this->currency,
            'leverage' => $this->leverage,
            'balance' => $this->balance,
            'equity' => $this->equity,
            'margin' => $this->margin,
            'free_margin' => $this->free_margin,
            'trading_enabled' => $this->trading_enabled,
            'risk_profile' => $this->riskProfile ? ['id' => $this->riskProfile->id, 'name' => $this->riskProfile->name] : null,
            'active_strategies' => $active,
            'capabilities' => $this->capabilities ?: (object) [],
            'synced_at' => $this->synced_at?->toIso8601String(),
            'created_at' => $this->created_at?->toIso8601String(),
        ];
    }
}
