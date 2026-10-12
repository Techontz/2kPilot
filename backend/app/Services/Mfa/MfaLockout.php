<?php

namespace App\Services\Mfa;

use App\Enums\AuditOutcome;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\RateLimiter;

/**
 * Wrong sign-in codes, counted per USER (not per session, device or IP):
 * after 5 misses in 15 minutes the code step is locked for that user for
 * 15 minutes. Shared by the web sign-in (AuthController) and the mobile app
 * sign-in (MobileAuthController), so switching clients never resets it.
 */
class MfaLockout
{
    public const MAX_MISSES = 5;

    public const LOCK_SECONDS = 900;

    public function __construct(private readonly AuditLogger $audit) {}

    public function locked(string $userId): bool
    {
        return Cache::has("mfa:locked:{$userId}");
    }

    /** Count a wrong code. True when this miss locked the user's code step. */
    public function miss(string $userId, ?User $user): bool
    {
        $this->audit->record('auth.mfa', AuditOutcome::Failure, $user, details: ['reason' => 'bad_code']);
        if (RateLimiter::hit("mfa-misses:{$userId}", self::LOCK_SECONDS) < self::MAX_MISSES) {
            return false;
        }
        RateLimiter::clear("mfa-misses:{$userId}");
        Cache::put("mfa:locked:{$userId}", true, self::LOCK_SECONDS);
        $this->audit->record('auth.mfa.locked', AuditOutcome::Denied, $user, 'user', $userId,
            details: ['misses' => self::MAX_MISSES, 'locked_minutes' => self::LOCK_SECONDS / 60]);

        return true;
    }

    public function passed(string $userId): void
    {
        RateLimiter::clear("mfa-misses:{$userId}");
    }

    public static function lockedResponse(): JsonResponse
    {
        return response()->json([
            'message' => 'Too many wrong codes. Wait 15 minutes, then sign in again.',
            'code' => 'mfa_locked',
        ], 429);
    }
}
