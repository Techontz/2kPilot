<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/** Immutable parameter set. Never updated: a change creates a new version. */
class StrategyVersion extends BaseModel
{
    use HasUuids;

    const UPDATED_AT = null;

    protected function casts(): array
    {
        return ['parameters' => 'array'];
    }

    public function strategy(): BelongsTo
    {
        return $this->belongsTo(Strategy::class);
    }
}
