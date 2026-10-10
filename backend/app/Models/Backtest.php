<?php

namespace App\Models;

use App\Enums\BacktestStatus;
use App\Models\Concerns\BelongsToUser;
use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Backtest extends BaseModel
{
    use BelongsToUser, HasUuids;

    const UPDATED_AT = null;

    protected function casts(): array
    {
        return [
            'status' => BacktestStatus::class,
            'parameters' => 'array',
            'risk_settings' => 'array',
            'costs' => 'array',
            'config' => 'array',
            'metrics' => 'array',
            'report' => 'array',
            'start' => 'datetime',
            'end' => 'datetime',
            'started_at' => 'datetime',
            'finished_at' => 'datetime',
        ];
    }

    public function children(): HasMany
    {
        return $this->hasMany(Backtest::class, 'parent_id')->orderBy('created_at');
    }

    public function trades(): HasMany
    {
        return $this->hasMany(BacktestTrade::class)->orderBy('entry_time');
    }
}
