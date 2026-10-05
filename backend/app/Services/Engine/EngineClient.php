<?php

namespace App\Services\Engine;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Http\Client\Response;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;
use RuntimeException;

/**
 * Laravel → trading engine (Python, 127.0.0.1:8431).
 *
 * Every request is signed with HMAC-SHA256 over
 *   METHOD \n PATH?QUERY \n TIMESTAMP \n NONCE \n sha256(BODY)
 * using ENGINE_API_SECRET (see trading-engine/src/fxrobot/internal/auth.py).
 * The engine refuses unsigned, stale or replayed requests.
 */
class EngineClient
{
    public function __construct(
        private readonly string $baseUrl,
        private readonly ?string $secret,
        private readonly int $timeout = 30,
    ) {}

    public function get(string $path, array $query = []): array
    {
        return $this->send('GET', $path, $query);
    }

    public function post(string $path, array $body = [], ?int $timeout = null): array
    {
        return $this->send('POST', $path, [], $body, $timeout);
    }

    public function put(string $path, array $body = []): array
    {
        return $this->send('PUT', $path, [], $body);
    }

    public function send(string $method, string $path, array $query = [], ?array $body = null, ?int $timeout = null): array
    {
        if (strlen((string) $this->secret) < 32) {
            throw new RuntimeException('ENGINE_API_SECRET is not configured (run php artisan fx:keys).');
        }
        $target = $path.($query ? '?'.http_build_query($query, '', '&', PHP_QUERY_RFC3986) : '');
        $payload = $body === null ? '' : json_encode((object) $body, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
        $timestamp = (string) time();
        $nonce = Str::random(32);
        $signature = hash_hmac('sha256', implode("\n", [
            strtoupper($method), $target, $timestamp, $nonce, hash('sha256', $payload),
        ]), (string) $this->secret);

        $request = Http::timeout($timeout ?? $this->timeout)
            ->acceptJson()
            ->withHeaders([
                'X-Engine-Timestamp' => $timestamp,
                'X-Engine-Nonce' => $nonce,
                'X-Engine-Signature' => $signature,
                'X-Correlation-ID' => (string) Str::uuid(),
            ]);
        if ($body !== null) {
            $request = $request->withBody($payload, 'application/json');
        }

        try {
            $response = $request->send($method, $this->baseUrl.$target);
        } catch (ConnectionException) {
            throw EngineException::unreachable();
        }

        return $this->decode($response);
    }

    private function decode(Response $response): array
    {
        if ($response->successful()) {
            return (array) $response->json();
        }
        $error = (array) ($response->json('error') ?? []);
        $message = (string) ($error['message'] ?? 'The trading engine refused the request.');
        if ($response->status() === 401) {
            $message = 'The backend and the trading engine do not share the same ENGINE_API_SECRET.';
        }
        throw new EngineException($message, $response->status(), (string) ($error['code'] ?? 'engine_error'));
    }
}
