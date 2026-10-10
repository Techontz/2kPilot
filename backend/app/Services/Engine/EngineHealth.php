<?php

namespace App\Services\Engine;

use App\Models\SystemState;
use Carbon\CarbonImmutable;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Log;

/**
 * "Is the trading engine OK?" is three separate questions, answered separately:
 *
 *   1. service    — does the Python engine's HTTP API answer its signed health check?
 *   2. supervisor — is the automated-trading supervisor (the loop that evaluates
 *                   strategies) switched on, and is its heartbeat fresh?
 *   3. summary    — one plain-language line for the dashboard combining both.
 *
 * This is DISPLAY information only. Whether new orders are permitted stays with
 * the heartbeat-based checks in TradingControl/TradingStatus and the engine's own
 * risk rules: a healthy HTTP answer never means "trading is operational".
 */
class EngineHealth
{
    public const CACHE_KEY = 'engine:service-health';

    public function __construct(private readonly EngineClient $engine) {}

    /**
     * The service health, refreshed at most every few seconds (cached, so
     * dashboard polling by many users costs one engine call per interval).
     *
     * @return array{status: string, reachable: bool, supervisor_enabled: bool|null, version: string|null, checked_at: string, detail: string|null}
     */
    public function service(): array
    {
        $ttl = max(1, (int) config('tradepilot.engine.health_cache_seconds', 10));

        return Cache::remember(self::CACHE_KEY, $ttl, fn () => $this->probe());
    }

    /**
     * The last known service health without calling the engine (null if none is
     * cached). Used on Stop/Start/mode responses so they never wait on the network.
     */
    public function cachedService(): ?array
    {
        $cached = Cache::get(self::CACHE_KEY);

        return is_array($cached) ? $cached : null;
    }

    /** @return array{status: string, reachable: bool, supervisor_enabled: bool|null, version: string|null, checked_at: string, detail: string|null} */
    private function probe(): array
    {
        $timeout = max(1, (int) config('tradepilot.engine.health_timeout_seconds', 3));
        try {
            $health = $this->engine->send('GET', '/internal/health', timeout: $timeout);
        } catch (EngineException $e) {
            Log::warning('Engine health check failed', ['code' => $e->errorCode, 'status' => $e->httpStatus()]);
            if ($e->errorCode === 'engine_unreachable') {
                return self::serviceResult('unreachable', false, null, null, 'The trading engine could not be reached.');
            }

            // It answered, but not healthily (its database is down, or the shared secret differs).
            return self::serviceResult('error', true, null, null, 'The trading engine answered but reported a problem.');
        } catch (\RuntimeException $e) {
            // Not configured on this server (no ENGINE_API_SECRET): nothing to call.
            Log::warning('Engine health check not possible', ['error' => $e->getMessage()]);

            return self::serviceResult('unreachable', false, null, null, 'The trading engine is not configured on this server.');
        }
        $ok = ($health['status'] ?? null) === 'ok';

        return self::serviceResult(
            $ok ? 'online' : 'error',
            true,
            array_key_exists('engine_enabled', $health) ? (bool) $health['engine_enabled'] : null,
            isset($health['version']) ? (string) $health['version'] : null,
            $ok ? null : 'The trading engine answered but reported a problem.',
        );
    }

    /** @return array{status: string, reachable: bool, supervisor_enabled: bool|null, version: string|null, checked_at: string, detail: string|null} */
    public static function serviceResult(string $status, bool $reachable, ?bool $supervisorEnabled, ?string $version, ?string $detail): array
    {
        return [
            'status' => $status,                         // online | error | unreachable
            'reachable' => $reachable,
            'supervisor_enabled' => $supervisorEnabled,  // the engine's ENGINE_ENABLED, when known
            'version' => $version,
            'checked_at' => now()->toIso8601String(),
            'detail' => $detail,
        ];
    }

    /**
     * Supervisor state from the service answer plus the heartbeat Laravel reads
     * from system_state. `$service` may be null (not checked yet).
     *
     * @return array{state: string, heartbeat_at: string|null, detail: string}
     */
    public static function supervisor(?array $service, SystemState $platform, int $freshSeconds): array
    {
        $beat = $platform->engine_heartbeat_at;
        $at = $beat?->toIso8601String();
        if ($service !== null && ! $service['reachable']) {
            return ['state' => 'unknown', 'heartbeat_at' => $at, 'detail' => 'Unknown while the trading engine cannot be reached.'];
        }
        if (($service['supervisor_enabled'] ?? null) === false) {
            return ['state' => 'disabled', 'heartbeat_at' => $at, 'detail' => 'Automated trading is switched off on this server.'];
        }
        if ($beat === null) {
            return ['state' => 'not_started', 'heartbeat_at' => null, 'detail' => 'The trading supervisor has not reported a heartbeat yet.'];
        }
        if (CarbonImmutable::parse($beat)->lt(now()->subSeconds($freshSeconds))) {
            return ['state' => 'stale', 'heartbeat_at' => $at, 'detail' => 'No heartbeat from the trading supervisor since '.$beat->format('Y-m-d H:i').' UTC.'];
        }
        if ($platform->engine_degraded) {
            return ['state' => 'degraded', 'heartbeat_at' => $at, 'detail' => $platform->engine_detail ?: 'Some accounts have problems.'];
        }

        return ['state' => 'running', 'heartbeat_at' => $at, 'detail' => $platform->engine_detail ?: 'Running.'];
    }

    /**
     * One dashboard line. `code` is stable for the UI; `tone` is
     * ok | info | warning | error.
     *
     * @return array{code: string, tone: string, label: string, message: string, trading_active: bool}
     */
    public static function summary(?array $service, array $supervisor): array
    {
        if ($service !== null && ! $service['reachable']) {
            return self::line('engine_offline', 'error', 'Engine offline',
                'The trading engine cannot be reached, so nothing will trade until it is back.', false);
        }
        if ($service !== null && $service['status'] === 'error') {
            return self::line('engine_error', 'error', 'Engine needs attention',
                'The trading engine is answering but reports a problem, so automated trading may not run.', false);
        }

        return match ($supervisor['state']) {
            'disabled' => self::line('trading_disabled', 'info', 'Engine online — automated trading disabled',
                'The engine is healthy, but automated trading is switched off on this server. No strategy will open trades.', false),
            'not_started' => self::line('supervisor_not_started', 'warning', 'Trading supervisor not started',
                $service === null
                    ? 'The trading supervisor has not reported in yet, so nothing will trade.'
                    : 'The engine is online, but its trading supervisor has not reported in yet, so nothing will trade.', false),
            'stale' => self::line('supervisor_stale', 'warning', 'Trading supervisor not responding',
                $supervisor['detail'].' Nothing will trade until it reports again.', false),
            'degraded' => self::line('running_degraded', 'warning', 'Running · attention', $supervisor['detail'], true),
            default => self::line('running', 'ok', 'Engine running', 'Automated trading is active. Every order still passes your risk limits.', true),
        };
    }

    /** @return array{code: string, tone: string, label: string, message: string, trading_active: bool} */
    private static function line(string $code, string $tone, string $label, string $message, bool $active): array
    {
        return ['code' => $code, 'tone' => $tone, 'label' => $label, 'message' => $message, 'trading_active' => $active];
    }
}
