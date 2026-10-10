<?php

namespace App\Models;

use App\Models\Concerns\BelongsToUser;

/**
 * In-app notification (table `notifications`), written by the engine and by
 * Laravel. `user_id` is the recipient; NULL = platform notification for admins.
 */
class AppNotification extends BaseModel
{
    use BelongsToUser;

    protected $table = 'notifications';

    const UPDATED_AT = null;

    protected function casts(): array
    {
        return ['data' => 'array', 'read_at' => 'datetime'];
    }
}
