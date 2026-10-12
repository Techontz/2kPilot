<?php

namespace App\Http\Controllers\Api;

use App\Enums\AuditOutcome;
use App\Exceptions\DomainException;
use App\Http\Controllers\Controller;
use App\Models\User;
use App\Providers\AppServiceProvider;
use App\Services\Audit\AuditLogger;
use App\Services\Mfa\MfaLockout;
use App\Services\Mfa\TwoFactorService;
use App\Services\Mobile\MobileMfaChallenges;
use App\Services\Mobile\MobileTokens;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\RateLimiter;
use Laravel\Sanctum\PersonalAccessToken;

/**
 * Sign-in for the 2kPilot mobile app: Sanctum bearer tokens instead of the
 * dashboard's cookie session. Same rules as the web sign-in (AuthController):
 * the same generic error and timing for unknown emails, the same "login"
 * throttle, the same per-user wrong-code lockout. With MFA on, the password
 * step returns a single-use 5-minute `mfa_token` (MobileMfaChallenges) and
 * the token is issued only after the code.
 *
 * Also: the user's signed-in devices (GET/DELETE /api/auth/tokens), which
 * the dashboard can use too.
 */
class MobileAuthController extends Controller
{
    public function __construct(
        private readonly AuditLogger $audit,
        private readonly TwoFactorService $mfa,
        private readonly MfaLockout $lockout,
        private readonly MobileMfaChallenges $challenges,
        private readonly MobileTokens $tokens,
    ) {}

    public function login(Request $request): JsonResponse
    {
        $data = $request->validate([
            'email' => ['required', 'string', 'email', 'max:320'],
            'password' => ['required', 'string', 'max:200'],
            'device_name' => ['required', 'string', 'min:1', 'max:100'],
        ]);
        $user = User::query()->where('email', strtolower(trim($data['email'])))->first();
        // Always one hash check, so response time does not reveal unknown emails.
        $passwordOk = Hash::check($data['password'], $user?->password ?? AuthController::timingHash());
        if ($user === null || ! $user->is_active || ! $passwordOk) {
            $this->audit->record('auth.mobile_login', AuditOutcome::Failure, $user, actorLabel: strtolower($data['email']),
                details: ['reason' => $user === null ? 'unknown_email' : (! $user->is_active ? 'inactive' : 'bad_password')]);

            return response()->json(['message' => 'Email or password is incorrect.', 'code' => 'invalid_credentials'], 422);
        }
        if (! $user->isApproved()) {
            return response()->json([
                'message' => 'Your account is waiting for an administrator to approve it.',
                'code' => 'approval_pending',
            ], 403);
        }
        $deviceName = trim($data['device_name']) ?: 'Mobile';
        if ($user->hasMfa()) {
            return response()->json([
                'mfa_required' => true,
                'mfa_token' => $this->challenges->issue($user->id, $deviceName),
            ]);
        }

        return $this->issueToken($user, $deviceName, false);
    }

    public function challenge(Request $request): JsonResponse
    {
        $data = $request->validate([
            'mfa_token' => ['required', 'string', 'max:200'],
            'code' => ['required', 'string', 'max:20'],
        ]);
        $pending = $this->challenges->find($data['mfa_token']);
        if ($pending === null) {
            return response()->json(['message' => 'Your sign-in expired. Enter your password again.', 'code' => 'mfa_expired'], 422);
        }
        $userId = (string) $pending['user_id'];
        if ($this->lockout->locked($userId)) {
            $this->challenges->consume($data['mfa_token']);

            return MfaLockout::lockedResponse();
        }
        $user = User::query()->find($userId);
        if ($user === null || ! $user->is_active || ! $this->mfa->verify($user, $data['code'])) {
            if ($this->lockout->miss($userId, $user)) {
                $this->challenges->consume($data['mfa_token']);

                return MfaLockout::lockedResponse();
            }

            return response()->json(['message' => 'That code is not valid.', 'code' => 'invalid_code'], 422);
        }
        $this->challenges->consume($data['mfa_token']);
        $this->lockout->passed($userId);
        // Both factors passed: the password step of this sign-in no longer counts against the email.
        RateLimiter::clear(md5('login'.AppServiceProvider::loginKey($user->email)));

        return $this->issueToken($user, (string) $pending['device_name'], true);
    }

    /** Sign this device out: its token and its push registration. */
    public function logout(Request $request): JsonResponse
    {
        /** @var PersonalAccessToken $token */
        $token = $request->user()->currentAccessToken();
        $this->tokens->revoke($token);
        $this->audit->record('auth.mobile_logout', actor: $request->user(), targetType: 'personal_access_token', targetId: (string) $token->id,
            details: ['device_name' => $token->name]);

        return response()->json(['ok' => true]);
    }

    /** The user's signed-in mobile devices. */
    public function tokens(Request $request): JsonResponse
    {
        $current = $request->user()->currentAccessToken();
        $currentId = $current instanceof PersonalAccessToken ? $current->id : null;

        return response()->json($request->user()->tokens()->orderByDesc('id')->get()
            ->map(fn (PersonalAccessToken $token) => [
                'id' => $token->id,
                'name' => $token->name,
                'created_at' => $token->created_at?->toIso8601String(),
                'last_used_at' => $token->last_used_at?->toIso8601String(),
                'expires_at' => $token->expires_at?->toIso8601String(),
                'current' => $token->id === $currentId,
            ])->values());
    }

    /** Sign one of the user's own devices out (404 for anyone else's). */
    public function revokeToken(Request $request, string $id): JsonResponse
    {
        $token = ctype_digit($id) ? $request->user()->tokens()->whereKey((int) $id)->first() : null;
        if (! $token instanceof PersonalAccessToken) {
            throw new DomainException('That device was not found.', 404, 'not_found');
        }
        $this->tokens->revoke($token);
        $this->audit->record('auth.token_revoked', actor: $request->user(), targetType: 'personal_access_token', targetId: (string) $token->id,
            details: ['scope' => 'one', 'device_name' => $token->name]);

        return response()->json(['ok' => true]);
    }

    private function issueToken(User $user, string $deviceName, bool $withMfa): JsonResponse
    {
        $issued = $this->tokens->issue($user, $deviceName);
        $user->forceFill(['last_login_at' => now()])->save();
        $this->audit->record('auth.mobile_login', actor: $user, targetType: 'personal_access_token', targetId: (string) $issued['token_id'],
            details: ['mfa' => $withMfa, 'device_name' => $deviceName]);

        return response()->json([
            'token' => $issued['token'],
            'token_type' => $issued['token_type'],
            'expires_at' => $issued['expires_at'],
            'user' => AuthController::present($user),
        ]);
    }
}
