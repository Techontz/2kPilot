<?php

namespace App\Services\Mfa;

use App\Models\User;
use BaconQrCode\Renderer\Image\SvgImageBackEnd;
use BaconQrCode\Renderer\ImageRenderer;
use BaconQrCode\Renderer\RendererStyle\RendererStyle;
use BaconQrCode\Writer;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Str;
use PragmaRX\Google2FA\Google2FA;

/**
 * Time-based one-time passwords (TOTP, RFC 6238) for any authenticator app,
 * plus single-use recovery codes. Secrets are stored encrypted (User casts).
 */
class TwoFactorService
{
    public function __construct(private readonly Google2FA $google2fa = new Google2FA) {}

    /** Start enrolment: a new secret (not active until confirmed with a code). */
    public function begin(User $user): array
    {
        $secret = $this->google2fa->generateSecretKey(32);
        $user->forceFill(['two_factor_secret' => $secret, 'two_factor_confirmed_at' => null])->save();
        $uri = $this->google2fa->getQRCodeUrl((string) config('tradepilot.mfa.issuer'), $user->email, $secret);
        $svg = (new Writer(new ImageRenderer(new RendererStyle(192, 1), new SvgImageBackEnd)))->writeString($uri);

        return ['secret' => $secret, 'otpauth_url' => $uri, 'qr_svg' => $svg];
    }

    /** @return list<string> recovery codes, shown once */
    public function confirm(User $user, string $code): ?array
    {
        if ($user->two_factor_secret === null || ! $this->verifyTotp($user, $code)) {
            return null;
        }
        $codes = $this->newRecoveryCodes();
        $user->forceFill([
            'two_factor_confirmed_at' => now(),
            'two_factor_recovery_codes' => array_map(fn ($c) => hash('sha256', $c), $codes),
        ])->save();

        return $codes;
    }

    public function disable(User $user): void
    {
        $user->forceFill([
            'two_factor_secret' => null,
            'two_factor_recovery_codes' => null,
            'two_factor_confirmed_at' => null,
        ])->save();
    }

    /** Accepts a 6-digit code or a recovery code (which is then used up). */
    public function verify(User $user, string $code): bool
    {
        $code = trim($code);
        if (preg_match('/^\d{6}$/', $code)) {
            return $this->verifyTotp($user, $code);
        }

        return $this->useRecoveryCode($user, $code);
    }

    /** @return list<string> */
    public function regenerateRecoveryCodes(User $user): array
    {
        $codes = $this->newRecoveryCodes();
        $user->forceFill(['two_factor_recovery_codes' => array_map(fn ($c) => hash('sha256', $c), $codes)])->save();

        return $codes;
    }

    private function verifyTotp(User $user, string $code): bool
    {
        if (! preg_match('/^\d{6}$/', $code) || $user->two_factor_secret === null) {
            return false;
        }
        $timestamp = $this->google2fa->verifyKeyNewer($user->two_factor_secret, $code, $this->lastUsedTimestamp($user), 1);
        if ($timestamp === false) {
            return false;
        }
        // A code can only be used once (replay protection).
        Cache::put("mfa:last:{$user->id}", $timestamp === true ? $this->google2fa->getTimestamp() : $timestamp, now()->addMinutes(5));

        return true;
    }

    private function lastUsedTimestamp(User $user): ?int
    {
        $value = Cache::get("mfa:last:{$user->id}");

        return is_int($value) ? $value : null;
    }

    private function useRecoveryCode(User $user, string $code): bool
    {
        $hash = hash('sha256', strtoupper(str_replace(' ', '', $code)));
        $codes = $user->two_factor_recovery_codes ?? [];
        if (! in_array($hash, $codes, true)) {
            return false;
        }
        $user->forceFill(['two_factor_recovery_codes' => array_values(array_diff($codes, [$hash]))])->save();

        return true;
    }

    /** @return list<string> */
    private function newRecoveryCodes(): array
    {
        return array_map(
            fn () => strtoupper(Str::random(5).'-'.Str::random(5)),
            range(1, (int) config('tradepilot.mfa.recovery_codes', 8)),
        );
    }
}
