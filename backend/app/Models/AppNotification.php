<?php

namespace App\Models;

/** In-app notification (table `notifications`), written by the engine and by Laravel. */
class AppNotification extends BaseModel
{
    protected $table = 'notifications';

    const UPDATED_AT = null;

    protected function casts(): array
    {
        return ['data' => 'array', 'read_at' => 'datetime'];
    }
}
