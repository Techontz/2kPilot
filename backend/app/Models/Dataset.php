<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUuids;

/** A stored candle series (CSV import, broker download, or SYNTHETIC test data). */
class Dataset extends BaseModel
{
    use HasUuids;

    protected function casts(): array
    {
        return ['first_bar' => 'datetime', 'last_bar' => 'datetime'];
    }

    public function isSynthetic(): bool
    {
        return $this->source === 'synthetic';
    }
}
