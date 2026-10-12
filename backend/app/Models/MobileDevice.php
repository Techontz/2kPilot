<?php

namespace App\Models;

use App\Models\Concerns\BelongsToUser;

/**
 * A phone registered for push notifications (Firebase Cloud Messaging).
 * Linked to the user and to the mobile token it was registered with, so
 * signing that device out removes it. The FCM token is unique through
 * `fcm_token_hash` (SHA-256): the token itself can exceed an index's length.
 */
class MobileDevice extends BaseModel
{
    use BelongsToUser;

    protected $hidden = ['fcm_token', 'fcm_token_hash'];

    protected function casts(): array
    {
        return ['last_seen_at' => 'datetime'];
    }

    public static function hashToken(string $fcmToken): string
    {
        return hash('sha256', $fcmToken);
    }
}
