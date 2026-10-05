<?php

namespace App\Http\Controllers\Api;

use App\Enums\AuditOutcome;
use App\Http\Controllers\Controller;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use App\Services\Mfa\TwoFactorService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\Hash;

/**
 * Login → (if MFA is on) one-time code → session.
 *
 * The session is only authenticated AFTER the second factor: until then the
 * user id waits in the session for 5 minutes under `mfa.pending`.
 */
class AuthController extends Controller
{
    private const MFA_WINDOW_SECONDS = 300;

    public function __construct(private readonly AuditLogger $audit, private readonly TwoFactorService $mfa) {}

    public function login(Request $request): JsonResponse
    {
        $data = $request->validate([
            'email' => ['required', 'string', 'email', 'max:320'],
            'password' => ['required', 'string', 'max:200'],
        ]);
        $user = User::query()->where('email', strtolower(trim($data['email'])))->first();
        if ($user === null || ! $user->is_active || ! Hash::check($data['password'], $user->password)) {
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
        $user = User::query()->find($pending['user_id']);
        if ($user === null || ! $user->is_active || ! $this->mfa->verify($user, $data['code'])) {
            $this->audit->record('auth.mfa', AuditOutcome::Failure, $user, details: ['reason' => 'bad_code']);

            return response()->json(['message' => 'That code is not valid.', 'code' => 'invalid_code'], 422);
        }
        $request->session()->forget('mfa.pending');

        return $this->completeLogin($request, $user, true);
    }

    public function logout(Request $request): JsonResponse
    {
        $user = $request->user();
        Auth::guard('web')->logout();
        $request->session()->invalidate();
        $request->session()->regenerateToken();
        if ($user) {
            $this->audit->record('auth.logout', actor: $user);
        }

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
            'mfa_required' => (bool) config('fx.mfa.required'),
            'last_login_at' => $user->last_login_at?->toIso8601String(),
        ];
    }
}
