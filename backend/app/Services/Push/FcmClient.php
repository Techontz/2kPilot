<?php

namespace App\Services\Push;

use Firebase\JWT\JWT;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Throwable;

/**
 * Firebase Cloud Messaging, HTTP v1 API.
 *
 * Authentication: a Google service account (FCM_CREDENTIALS = path to its
 * JSON key, kept outside the web root). We sign a short JWT with its private
 * key (RS256, firebase/php-jwt) and exchange it at Google's token endpoint
 * (JWT bearer grant) for a one-hour OAuth2 access token, cached until shortly
 * before it expires. Then one POST per device to
 * https://fcm.googleapis.com/v1/projects/{FCM_PROJECT_ID}/messages:send.
 *
 * Not configured (no project id or no readable key file) = push is off: every
 * call is a no-op, logged once at debug level, never an error.
 */
class FcmClient
{
    public const SCOPE = 'https://www.googleapis.com/auth/firebase.messaging';

    public const TOKEN_URL = 'https://oauth2.googleapis.com/token';

    /** Delivered. */
    public const OK = 'ok';

    /** FCM says the device token is dead (UNREGISTERED / INVALID_ARGUMENT): delete it. */
    public const INVALID = 'invalid';

    /** Rate limited or FCM unavailable: worth retrying later. */
    public const RETRY = 'retry';

    /** Anything else (bad credentials, network…): logged, not retried. */
    public const FAILED = 'failed';

    private const ACCESS_TOKEN_CACHE_KEY = 'push:fcm:access-token';

    private static bool $loggedUnconfigured = false;

    /** Seconds FCM asked us to wait (Retry-After) on the last RETRY answer. */
    public ?int $retryAfter = null;

    private ?array $credentials = null;

    public function configured(): bool
    {
        if ($this->projectId() !== null && $this->credentials() !== null) {
            return true;
        }
        if (! self::$loggedUnconfigured) {
            self::$loggedUnconfigured = true;
            Log::debug('Push notifications are off: set FCM_PROJECT_ID and FCM_CREDENTIALS to enable them.');
        }

        return false;
    }

    /**
     * Send one message (the FCM v1 `message` object without `token`) to one device.
     *
     * @return self::OK|self::INVALID|self::RETRY|self::FAILED
     */
    public function send(string $deviceToken, array $message): string
    {
        $this->retryAfter = null;
        if (! $this->configured()) {
            return self::FAILED;
        }
        try {
            $accessToken = $this->accessToken();
            if ($accessToken === null) {
                return self::FAILED;
            }
            $response = Http::withToken($accessToken)->acceptJson()
                ->timeout((int) config('tradepilot.push.timeout', 10))
                ->post("https://fcm.googleapis.com/v1/projects/{$this->projectId()}/messages:send",
                    ['message' => ['token' => $deviceToken] + $message]);
        } catch (ConnectionException) {
            return self::RETRY;
        } catch (Throwable $e) {
            Log::warning('Push notification failed', ['error' => $e->getMessage()]);

            return self::FAILED;
        }
        if ($response->successful()) {
            return self::OK;
        }
        $status = $response->status();
        $error = (string) ($response->json('error.status') ?? '');
        $fcmCode = collect((array) $response->json('error.details'))->pluck('errorCode')->filter()->first();
        if ($status === 404 || in_array($error, ['NOT_FOUND', 'INVALID_ARGUMENT'], true)
            || in_array($fcmCode, ['UNREGISTERED', 'INVALID_ARGUMENT'], true)) {
            return self::INVALID;
        }
        if ($status === 401) {
            Cache::forget(self::ACCESS_TOKEN_CACHE_KEY); // expired or revoked: fetch a new one next time

            return self::RETRY;
        }
        if ($status === 429 || $status >= 500) {
            $after = $response->header('Retry-After');
            $this->retryAfter = is_numeric($after) ? max(1, min(3600, (int) $after)) : null;

            return self::RETRY;
        }
        Log::warning('Push notification refused by FCM', ['status' => $status, 'error' => $error ?: null, 'fcm_code' => $fcmCode]);

        return self::FAILED;
    }

    /** OAuth2 access token for the service account (cached; null if Google refused). */
    private function accessToken(): ?string
    {
        $cached = Cache::get(self::ACCESS_TOKEN_CACHE_KEY);
        if (is_string($cached) && $cached !== '') {
            return $cached;
        }
        $credentials = $this->credentials();
        $tokenUrl = $credentials['token_uri'] ?? self::TOKEN_URL;
        $now = time();
        $assertion = JWT::encode([
            'iss' => $credentials['client_email'],
            'sub' => $credentials['client_email'],
            'scope' => self::SCOPE,
            'aud' => $tokenUrl,
            'iat' => $now,
            'exp' => $now + 3600,
        ], $credentials['private_key'], 'RS256', $credentials['private_key_id'] ?? null);
        $response = Http::asForm()->acceptJson()->timeout((int) config('tradepilot.push.timeout', 10))->post($tokenUrl, [
            'grant_type' => 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion' => $assertion,
        ]);
        $token = $response->json('access_token');
        if (! $response->successful() || ! is_string($token) || $token === '') {
            Log::warning('Push notifications: Google refused the service account', ['status' => $response->status(), 'error' => $response->json('error')]);

            return null;
        }
        $ttl = max(60, (int) ($response->json('expires_in') ?? 3600) - 300);
        Cache::put(self::ACCESS_TOKEN_CACHE_KEY, $token, $ttl);

        return $token;
    }

    private function projectId(): ?string
    {
        $id = trim((string) config('tradepilot.push.project_id'));

        return $id !== '' ? $id : null;
    }

    /** @return array{client_email: string, private_key: string, token_uri?: string, private_key_id?: string}|null */
    private function credentials(): ?array
    {
        if ($this->credentials !== null) {
            return $this->credentials;
        }
        $path = trim((string) config('tradepilot.push.credentials'));
        if ($path === '' || ! is_file($path) || ! is_readable($path)) {
            return null;
        }
        $json = json_decode((string) file_get_contents($path), true);
        if (! is_array($json) || empty($json['client_email']) || empty($json['private_key'])) {
            return null;
        }

        return $this->credentials = $json;
    }
}
