<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;
use Illuminate\Database\Eloquent\Relations\HasMany;

class Strategy extends BaseModel
{
    use HasUuids;

    public function versions(): HasMany
    {
        return $this->hasMany(StrategyVersion::class)->orderBy('version');
    }

    public function assignments(): HasMany
    {
        return $this->hasMany(StrategyAssignment::class);
    }
}
