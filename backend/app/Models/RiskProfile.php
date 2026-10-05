<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\HasMany;

/** Risk limits assigned to trading accounts. NULL = this optional limit is off. */
class RiskProfile extends BaseModel
{
    use HasUuids;

    public const DEFAULT_NAME = 'Conservative (default)';

    protected function casts(): array
    {
        return ['allowed_sessions' => 'array'];
    }

    public function accounts(): HasMany
    {
        return $this->hasMany(TradingAccount::class);
    }
}
