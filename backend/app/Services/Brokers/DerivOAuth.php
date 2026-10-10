<?php

namespace App\Services\Brokers;

use App\Exceptions\DomainException;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;

/**
 * Deriv sign-in: OAuth 2.0 Authorization Code + PKCE (auth.deriv.com).
 *
 *   1. start(): random `state` + `code_verifier` are kept in the session; the
 *      browser goes to https://auth.deriv.com/oauth2/auth with the S256 challenge.
 *   2. Deriv redirects back with ?code&state; exchange() checks `state` and swaps
 *      the code (with the verifier) for an access token — server-side only.
 *
 * Access tokens last about one hour; for 24/7 automated trading a personal
 * access token is more robust (documented in docs/BROKERS.md).
 *
 * Local development: Deriv's web application firewall answers 403 "Access Denied"
 * to any /oauth2/auth or /oauth2/token request whose `redirect_uri` points at a
 * loopback host (localhost, 127.0.0.1, ::1). For those we leave `redirect_uri`
 * out of both requests; Deriv then uses the redirect URL registered for the app,
 * which must be exactly DERIV_OAUTH_REDIRECT_URL (see docs/BROKERS.md).
 */
class DerivOAuth
{
    public const AUTHORIZE_URL = 'https://auth.deriv.com/oauth2/auth';

    public const TOKEN_URL = 'https://auth.deriv.com/oauth2/token';

    public function enabled(): bool
    {
        return (bool) config('tradepilot.deriv.app_id') && (bool) config('tradepilot.deriv.oauth_redirect_url');
    }

    /** @return array{url: string, state: string, verifier: string} */
    public function start(): array
    {
        if (! $this->enabled()) {
            throw new DomainException('Deriv sign-in needs DERIV_APP_ID and DERIV_OAUTH_REDIRECT_URL in backend/.env.', 422, 'deriv_not_configured');
        }
        $state = Str::random(40);
        $verifier = Str::random(64);
        $challenge = rtrim(strtr(base64_encode(hash('sha256', $verifier, true)), '+/', '-_'), '=');
        $url = self::AUTHORIZE_URL.'?'.http_build_query([
            'response_type' => 'code',
            'client_id' => config('tradepilot.deriv.app_id'),
            ...$this->redirectParam(),
            'scope' => 'trade',
            'state' => $state,
            'code_challenge' => $challenge,
            'code_challenge_method' => 'S256',
        ], '', '&', PHP_QUERY_RFC3986);

        return ['url' => $url, 'state' => $state, 'verifier' => $verifier];
    }

    /** @return array{access_token: string, expires_in: int|null, refresh_token: string|null} */
    public function exchange(string $code, string $verifier): array
    {
        try {
            $response = Http::asForm()->acceptJson()->timeout(20)->post(self::TOKEN_URL, [
                'grant_type' => 'authorization_code',
                'client_id' => config('tradepilot.deriv.app_id'),
                'code' => $code,
                ...$this->redirectParam(),
                'code_verifier' => $verifier,
            ]);
        } catch (ConnectionException) {
            throw new DomainException('Could not reach Deriv to finish signing in.', 502, 'deriv_unreachable');
        }
        $token = $response->json('access_token');
        if (! $response->successful() || ! is_string($token) || $token === '') {
            $error = (string) ($response->json('error') ?? 'invalid_grant');
            throw new DomainException("Deriv sign-in failed ({$error}). Please try again.", 422, 'deriv_oauth_failed');
        }

        return [
            'access_token' => $token,
            'expires_in' => is_numeric($response->json('expires_in')) ? (int) $response->json('expires_in') : null,
            'refresh_token' => $response->json('refresh_token') ?: null,
        ];
    }

    /**
     * `redirect_uri` for both OAuth requests — omitted for loopback hosts, which
     * Deriv's firewall blocks (Deriv falls back to the app's registered URL).
     *
     * @return array<string, string>
     */
    private function redirectParam(): array
    {
        $url = (string) config('tradepilot.deriv.oauth_redirect_url');

        return self::isLoopback($url) ? [] : ['redirect_uri' => $url];
    }

    public static function isLoopback(string $url): bool
    {
        $host = strtolower(trim((string) parse_url($url, PHP_URL_HOST), '[]'));

        return $host === 'localhost' || str_ends_with($host, '.localhost') || $host === '::1'
            || (filter_var($host, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) !== false && str_starts_with($host, '127.'));
    }
}
