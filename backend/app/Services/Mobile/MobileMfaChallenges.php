<?php

namespace App\Services\Mobile;

use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Str;

/**
 * The mobile sign-in's pending second factor. The app has no session, so a
 * correct password returns an opaque `mfa_token` instead: a random,
 * single-use id valid for 5 minutes. Only its SHA-256 is stored (in the
 * cache) with the user id and device name; the code step consumes it on
 * success or lockout.
 */
class MobileMfaChallenges
{
    public const TTL_SECONDS = 300;

    public function issue(string $userId, string $deviceName): string
    {
        $token = Str::random(64);
        Cache::put(self::key($token), ['user_id' => $userId, 'device_name' => $deviceName], self::TTL_SECONDS);

        return $token;
    }

    /** @return array{user_id: string, device_name: string}|null */
    public function find(?string $token): ?array
    {
        if (! is_string($token) || $token === '' || strlen($token) > 200) {
            return null;
        }
        $pending = Cache::get(self::key($token));

        return is_array($pending) ? $pending : null;
    }

    public function consume(string $token): void
    {
        Cache::forget(self::key($token));
    }

    private static function key(string $token): string
    {
        return 'mobile-mfa:'.hash('sha256', $token);
    }
}
