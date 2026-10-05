<?php

namespace App\Http\Controllers\Api;

use App\Enums\AuditOutcome;
use App\Exceptions\DomainException;
use App\Http\Controllers\Controller;
use App\Services\Audit\AuditLogger;
use App\Services\Mfa\TwoFactorService;
use App\Services\Notifier;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Hash;

/** Settings → Security: turn two-factor authentication on or off. */
class MfaController extends Controller
{
    public function __construct(
        private readonly TwoFactorService $mfa,
        private readonly AuditLogger $audit,
        private readonly Notifier $notifier,
    ) {}

    public function setup(Request $request): JsonResponse
    {
        $request->validate(['password' => ['required', 'string']]);
        $user = $request->user();
        $this->checkPassword($request);
        if ($user->hasMfa()) {
            throw DomainException::conflict('Two-factor authentication is already on.');
        }
        $this->audit->record('auth.mfa.setup_started', actor: $user);

        return response()->json($this->mfa->begin($user));
    }

    public function confirm(Request $request): JsonResponse
    {
        $data = $request->validate(['code' => ['required', 'digits:6']]);
        $user = $request->user();
        $codes = $this->mfa->confirm($user, $data['code']);
        if ($codes === null) {
            $this->audit->record('auth.mfa.enabled', AuditOutcome::Failure, $user, details: ['reason' => 'bad_code']);

            return response()->json(['message' => 'That code is not valid. Check the time on your phone and try again.', 'code' => 'invalid_code'], 422);
        }
        $this->audit->record('auth.mfa.enabled', actor: $user);
        $this->notifier->notify('security.mfa', "Two-factor authentication turned on for {$user->email}.");

        return response()->json(['recovery_codes' => $codes]);
    }

    public function disable(Request $request): JsonResponse
    {
        $data = $request->validate(['password' => ['required', 'string'], 'code' => ['required', 'string', 'max:20']]);
        $user = $request->user();
        $this->checkPassword($request);
        if (! $this->mfa->verify($user, $data['code'])) {
            $this->audit->record('auth.mfa.disabled', AuditOutcome::Denied, $user, details: ['reason' => 'bad_code']);

            return response()->json(['message' => 'That code is not valid.', 'code' => 'invalid_code'], 422);
        }
        $this->mfa->disable($user);
        $this->audit->record('auth.mfa.disabled', actor: $user);
        $this->notifier->notify('security.mfa', "Two-factor authentication turned OFF for {$user->email}.");

        return response()->json(['ok' => true]);
    }

    public function recoveryCodes(Request $request): JsonResponse
    {
        $request->validate(['password' => ['required', 'string']]);
        $this->checkPassword($request);
        $user = $request->user();
        if (! $user->hasMfa()) {
            throw DomainException::conflict('Turn on two-factor authentication first.');
        }
        $this->audit->record('auth.mfa.recovery_codes_regenerated', actor: $user);

        return response()->json(['recovery_codes' => $this->mfa->regenerateRecoveryCodes($user)]);
    }

    private function checkPassword(Request $request): void
    {
        if (! Hash::check((string) $request->input('password'), $request->user()->password)) {
            $this->audit->record('auth.password_check', AuditOutcome::Denied, $request->user());
            throw new DomainException('Password is incorrect.', 422, 'password_incorrect');
        }
    }
}
