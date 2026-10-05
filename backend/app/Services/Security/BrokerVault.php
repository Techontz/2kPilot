<?php

namespace App\Services\Security;

use Illuminate\Encryption\Encrypter;
use RuntimeException;

/**
 * Encrypts broker credentials (tokens, passwords, bridge secrets) with
 * AES-256-GCM and BROKER_CREDENTIALS_KEY — a key separate from APP_KEY, shared
 * only with the trading engine, which decrypts them when it connects.
 *
 * Ciphertext is stored in broker_connections.credentials_encrypted and is
 * never returned by the API, written to logs, or sent to the browser.
 */
class BrokerVault
{
    private ?Encrypter $encrypter = null;

    public function __construct(private readonly ?string $key) {}

    public function configured(): bool
    {
        return $this->rawKey() !== null;
    }

    /** @param  array<string, string>  $credentials */
    public function seal(array $credentials): string
    {
        return $this->encrypter()->encryptString(json_encode($credentials, JSON_THROW_ON_ERROR));
    }

    /** @return array<string, string> Only for tests and tooling; the app never needs plaintext back. */
    public function open(string $ciphertext): array
    {
        return json_decode($this->encrypter()->decryptString($ciphertext), true, flags: JSON_THROW_ON_ERROR);
    }

    public static function generateKey(): string
    {
        return 'base64:'.base64_encode(random_bytes(32));
    }

    private function encrypter(): Encrypter
    {
        $key = $this->rawKey();
        if ($key === null) {
            throw new RuntimeException('BROKER_CREDENTIALS_KEY is not configured (run php artisan fx:keys).');
        }

        return $this->encrypter ??= new Encrypter($key, 'aes-256-gcm');
    }

    private function rawKey(): ?string
    {
        if (! $this->key) {
            return null;
        }
        $raw = str_starts_with($this->key, 'base64:') ? base64_decode(substr($this->key, 7), true) : null;

        return ($raw !== false && $raw !== null && strlen($raw) === 32) ? $raw : null;
    }
}
