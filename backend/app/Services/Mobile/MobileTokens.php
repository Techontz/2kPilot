<?php

namespace App\Services\Mobile;

use App\Models\MobileDevice;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use Illuminate\Support\Facades\DB;
use Laravel\Sanctum\PersonalAccessToken;

/**
 * The mobile app's Sanctum tokens: one per signed-in device, ability
 * "mobile", expiring after TP_MOBILE_TOKEN_DAYS (default 30). Revoking a
 * token also removes the push registration made with it, so a signed-out
 * phone stops receiving notifications.
 */
class MobileTokens
{
    public const ABILITY = 'mobile';

    public function __construct(private readonly AuditLogger $audit) {}

    /** @return array{token: string, token_type: string, expires_at: ?string} */
    public function issue(User $user, string $deviceName): array
    {
        $days = (int) config('tradepilot.mobile.token_days', 30);
        $new = $user->createToken($deviceName, [self::ABILITY], $days > 0 ? now()->addDays($days) : null);

        return [
            'token' => $new->plainTextToken,
            'token_type' => 'Bearer',
            'expires_at' => $new->accessToken->expires_at?->toIso8601String(),
            'token_id' => $new->accessToken->id,
        ];
    }

    /** Revoke one token (and its device's push registration). */
    public function revoke(PersonalAccessToken $token): void
    {
        DB::transaction(function () use ($token) {
            MobileDevice::query()->where('personal_access_token_id', $token->id)->delete();
            $token->delete();
        });
    }

    /**
     * Sign the user out of every mobile device: password changed, MFA turned
     * off, account deactivated. Returns how many tokens were revoked.
     */
    public function revokeAll(User $user, string $reason): int
    {
        $count = DB::transaction(function () use ($user) {
            MobileDevice::query()->where('user_id', $user->id)->delete();

            return $user->tokens()->delete();
        });
        if ($count > 0) {
            $this->audit->record('auth.token_revoked', actor: $user, targetType: 'user', targetId: $user->id,
                details: ['scope' => 'all', 'count' => $count, 'reason' => $reason]);
        }

        return $count;
    }
}
