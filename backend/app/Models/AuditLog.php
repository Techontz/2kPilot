<?php

namespace App\Models;

use App\Enums\AuditOutcome;

/** Append-only: the database refuses UPDATE and DELETE on this table. */
class AuditLog extends BaseModel
{
    public $timestamps = false;

    protected function casts(): array
    {
        return [
            'occurred_at' => 'datetime',
            'outcome' => AuditOutcome::class,
            'details' => 'array',
        ];
    }
}
