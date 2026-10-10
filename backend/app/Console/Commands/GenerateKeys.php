<?php

namespace App\Console\Commands;

use App\Services\Security\BrokerVault;
use Illuminate\Console\Command;
use Illuminate\Support\Str;

/**
 * Create the two shared secrets and write them to BOTH backend/.env and
 * trading-engine/.env (never overwriting existing values):
 *   BROKER_CREDENTIALS_KEY — encrypts broker tokens/passwords (AES-256-GCM)
 *   ENGINE_API_SECRET      — signs Laravel → engine requests (HMAC-SHA256)
 */
class GenerateKeys extends Command
{
    protected $signature = 'tp:keys {--engine-env= : Path to trading-engine/.env} {--force : Replace existing values}';

    protected $description = 'Generate BROKER_CREDENTIALS_KEY and ENGINE_API_SECRET for backend and trading engine';

    public function handle(): int
    {
        $backendEnv = base_path('.env');
        $engineEnv = $this->option('engine-env') ?: dirname(base_path()).'/trading-engine/.env';
        $current = $this->read($backendEnv);
        $values = [
            'BROKER_CREDENTIALS_KEY' => ($this->option('force') ? null : ($current['BROKER_CREDENTIALS_KEY'] ?? null)) ?: BrokerVault::generateKey(),
            'ENGINE_API_SECRET' => ($this->option('force') ? null : ($current['ENGINE_API_SECRET'] ?? null)) ?: Str::random(64),
        ];
        foreach ([$backendEnv, $engineEnv] as $path) {
            if (! file_exists($path)) {
                $this->warn("Skipped {$path} (file not found — create it from .env.example first).");

                continue;
            }
            $this->write($path, $values);
            $this->info("Updated {$path}");
        }
        $this->line('The same two values are now in both files. They are secrets: never commit them.');

        return self::SUCCESS;
    }

    private function read(string $path): array
    {
        $out = [];
        foreach (file_exists($path) ? file($path, FILE_IGNORE_NEW_LINES) : [] as $line) {
            if (preg_match('/^([A-Z0-9_]+)=(.*)$/', $line, $m)) {
                $out[$m[1]] = trim($m[2], '"');
            }
        }

        return $out;
    }

    private function write(string $path, array $values): void
    {
        $content = (string) file_get_contents($path);
        foreach ($values as $key => $value) {
            if (preg_match("/^{$key}=.*$/m", $content)) {
                $content = preg_replace("/^{$key}=.*$/m", "{$key}={$value}", $content);
            } else {
                $content = rtrim($content)."\n{$key}={$value}\n";
            }
        }
        file_put_contents($path, $content);
    }
}
