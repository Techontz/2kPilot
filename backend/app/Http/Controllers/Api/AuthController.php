<?php

namespace App\Http\Controllers\Api;

use App\Enums\AuditOutcome;
use App\Enums\UserRole;
use App\Exceptions\DomainException;
use App\Http\Controllers\Controller;
use App\Models\User;
use App\Providers\AppServiceProvider;
use App\Services\Audit\AuditLogger;
use App\Services\Mfa\MfaLockout;
use App\Services\Mfa\TwoFactorService;
use App\Services\Mobile\MobileTokens;
use App\Services\Notifier;
use App\Services\Trading\TradingControl;
use App\Services\Users\UserProvisioner;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\Str;
use Illuminate\Validation\Rules\Password;

/**
 * Sign-up → session, and login → (if MFA is on) one-time code → session.
 *
 * The session is only authenticated AFTER the second factor: until then the
 * user id waits in the session for 5 minutes under `mfa.pending`. Wrong codes
 * are counted per USER (not per session): after 5 misses in 15 minutes the
 * code step is locked for that user for 15 minutes.
 *
 * Neither answer tells whether an email has an account: unknown emails cost
 * the same password hash check, and a taken email gets a generic sign-up error.
 */
class AuthController extends Controller
{
    public const MFA_WINDOW_SECONDS = 300;

    public function __construct(
        private readonly AuditLogger $audit,
        private readonly TwoFactorService $mfa,
        private readonly UserProvisioner $provisioner,
        private readonly Notifier $notifier,
        private readonly TradingControl $control,
        private readonly MfaLockout $lockout,
        private readonly MobileTokens $tokens,
    ) {}

    /**
     * Public sign-up. The new user gets the "user" role, a Beginner risk
     * profile and trading STOPPED in DEMO mode, and is signed in.
     */
    public function register(Request $request): JsonResponse
    {
        if (! config('tradepilot.registration_enabled')) {
            throw DomainException::forbidden('Sign-up is closed on this server. Ask the administrator for an account.', 'registration_disabled');
        }
        $request->merge(['email' => strtolower(trim((string) $request->input('email')))]);
        $data = $request->validate([
            'name' => ['required', 'string', 'max:120'],
            'email' => ['required', 'string', 'email', 'max:320', 'unique:users,email'],
            'password' => ['required', 'string', 'max:200', 'confirmed', Password::defaults()],
            'accept_terms' => ['accepted'], // the risk disclosure
        ], ['email.unique' => "We couldn't create an account with these details."]);
        $user = DB::transaction(function () use ($data) {
            $user = User::query()->create([
                'name' => trim($data['name']),
                'email' => $data['email'],
                'password' => $data['password'],
                'role' => UserRole::User,
                'is_active' => true,
            ]);
            $this->provisioner->provision($user);

            return $user;
        });
        $this->audit->record('auth.registered', actor: $user, targetType: 'user', targetId: $user->id,
            details: ['email' => $user->email, 'accepted_risk_disclosure' => true]);

        return $this->completeLogin($request, $user, false)->setStatusCode(201);
    }

    public function login(Request $request): JsonResponse
    {
        $data = $request->validate([
            'email' => ['required', 'string', 'email', 'max:320'],
            'password' => ['required', 'string', 'max:200'],
        ]);
        $user = User::query()->where('email', strtolower(trim($data['email'])))->first();
        // Always one hash check, so response time does not reveal unknown emails.
        $passwordOk = Hash::check($data['password'], $user?->password ?? self::timingHash());
        if ($user === null || ! $user->is_active || ! $passwordOk) {
            $this->audit->record('auth.login', AuditOutcome::Failure, $user, actorLabel: strtolower($data['email']),
                details: ['reason' => $user === null ? 'unknown_email' : (! $user->is_active ? 'inactive' : 'bad_password')]);

            return response()->json(['message' => 'Email or password is incorrect.', 'code' => 'invalid_credentials'], 422);
        }
        if ($user->hasMfa()) {
            $request->session()->put('mfa.pending', ['user_id' => $user->id, 'until' => now()->timestamp + self::MFA_WINDOW_SECONDS]);

            return response()->json(['mfa_required' => true]);
        }

        return $this->completeLogin($request, $user, false);
    }

    public function challenge(Request $request): JsonResponse
    {
        $data = $request->validate(['code' => ['required', 'string', 'max:20']]);
        $pending = $request->session()->get('mfa.pending');
        if (! is_array($pending) || ($pending['until'] ?? 0) < now()->timestamp) {
            $request->session()->forget('mfa.pending');

            return response()->json(['message' => 'Your sign-in expired. Enter your password again.', 'code' => 'mfa_expired'], 422);
        }
        $userId = (string) $pending['user_id'];
        if ($this->lockout->locked($userId)) {
            $request->session()->forget('mfa.pending');

            return MfaLockout::lockedResponse();
        }
        $user = User::query()->find($userId);
        if ($user === null || ! $user->is_active || ! $this->mfa->verify($user, $data['code'])) {
            if ($this->lockout->miss($userId, $user)) {
                $request->session()->forget('mfa.pending');

                return MfaLockout::lockedResponse();
            }

            return response()->json(['message' => 'That code is not valid.', 'code' => 'invalid_code'], 422);
        }
        $request->session()->forget('mfa.pending');
        $this->lockout->passed($userId);
        // Both factors passed: the password step of this sign-in no longer counts against the email.
        RateLimiter::clear(md5('login'.AppServiceProvider::loginKey($user->email)));

        return $this->completeLogin($request, $user, true);
    }

    /** A real hash of a random secret, checked when the email is unknown. */
    public static function timingHash(): string
    {
        return Cache::rememberForever('auth:timing-hash', fn () => Hash::make(Str::random(40)));
    }

    public function logout(Request $request): JsonResponse
    {
        $user = $request->user();
        Auth::guard('web')->logout();
        if ($request->hasSession()) { // bearer-token requests have none (the app uses /api/mobile/auth/logout)
            $request->session()->invalidate();
            $request->session()->regenerateToken();
        }
        if ($user) {
            $this->audit->record('auth.logout', actor: $user);
        }

        return response()->json(['ok' => true]);
    }

    /**
     * Settings → Security: change the password. The current one is required;
     * the session id is renewed and this browser stays signed in (other
     * browsers are signed out on their next request: Sanctum compares the
     * password hash kept in each session). Every mobile app token is revoked.
     */
    public function changePassword(Request $request): JsonResponse
    {
        $data = $request->validate([
            'current_password' => ['required', 'string', 'max:200'],
            'password' => ['required', 'string', 'max:200', 'confirmed', 'different:current_password', Password::defaults()],
        ], ['password.different' => 'Choose a password different from your current one.']);
        $user = $request->user();
        if (! Hash::check($data['current_password'], $user->password)) {
            $this->audit->record('auth.password_changed', AuditOutcome::Denied, $user, 'user', $user->id, details: ['reason' => 'password_incorrect']);
            throw new DomainException('Your current password is incorrect.', 422, 'password_incorrect');
        }
        $user->forceFill(['password' => $data['password']])->save();
        $request->session()->regenerate();
        $this->audit->record('auth.password_changed', actor: $user, targetType: 'user', targetId: $user->id);
        $this->notifier->notify('security.password', "The password for {$user->email} was changed. If this was not you, contact your administrator.", $user->id);
        $this->control->revokeLiveIf($user->id, $user, 'your password was changed', fn () => true);
        $this->tokens->revokeAll($user, 'password_changed'); // the mobile app signs in again

        return response()->json(['ok' => true]);
    }

    public function me(Request $request): JsonResponse
    {
        return response()->json(['user' => $this->present($request->user())]);
    }

    private function completeLogin(Request $request, User $user, bool $withMfa): JsonResponse
    {
        Auth::guard('web')->login($user);
        $request->session()->regenerate(); // new session id: no session fixation
        $user->forceFill(['last_login_at' => now()])->save();
        $this->audit->record('auth.login', actor: $user, details: ['mfa' => $withMfa]);

        return response()->json(['user' => $this->present($user)]);
    }

    public static function present(User $user): array
    {
        return [
            'id' => $user->id,
            'name' => $user->name,
            'email' => $user->email,
            'role' => $user->role->value,
            'mfa_enabled' => $user->hasMfa(),
            'mfa_required' => (bool) config('tradepilot.mfa.required'),
            'last_login_at' => $user->last_login_at?->toIso8601String(),
        ];
    }
}
