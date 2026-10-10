<?php

namespace App\Models;

use App\Enums\AssignmentStatus;
use App\Models\Concerns\BelongsToAccount;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

/**
 * One strategy version running on one symbol of one account. Created PAUSED.
 * The contract columns say how its signals are traded (App\Support\ContractSpec).
 */
class StrategyAssignment extends BaseModel
{
    use BelongsToAccount, HasUuids;

    protected function casts(): array
    {
        return [
            'status' => AssignmentStatus::class,
            'last_bar_evaluated' => 'datetime',
            'last_signal_at' => 'datetime',
            'duration' => 'integer',
            'allow_equals' => 'boolean',
            'multiplier' => 'integer',
        ];
    }

    public function strategy(): BelongsTo
    {
        return $this->belongsTo(Strategy::class);
    }

    public function version(): BelongsTo
    {
        return $this->belongsTo(StrategyVersion::class, 'strategy_version_id');
    }

    public function account(): BelongsTo
    {
        return $this->belongsTo(TradingAccount::class, 'account_id');
    }

    public function evaluations(): HasMany
    {
        return $this->hasMany(StrategyEvaluation::class, 'assignment_id');
    }
}
