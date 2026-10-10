<?php

namespace App\Models;

use App\Models\Concerns\BelongsToUser;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\HasMany;

/**
 * A user's risk limits, assigned to their trading accounts. NULL = this
 * optional limit is off. Every user gets a "Beginner" profile at sign-up.
 * Pip/lot limits apply to SPOT trades; contracts are sized by stake_amount.
 */
class RiskProfile extends BaseModel
{
    use BelongsToUser, HasUuids;

    public const DEFAULT_NAME = 'Beginner';

    protected function casts(): array
    {
        return ['allowed_sessions' => 'array', 'max_consecutive_losses' => 'integer'];
    }

    public function accounts(): HasMany
    {
        return $this->hasMany(TradingAccount::class);
    }
}
