<?php

namespace App\Services\Trading;

use App\Enums\AuditOutcome;
use App\Enums\EngineState;
use App\Enums\TradingMode;
use App\Exceptions\DomainException;
use App\Models\SystemState;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use App\Services\Notifier;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Hash;

/**
 * Global controls: STOP TRADING (kill switch), resume, operating mode and the
 * separate "Close positions" emergency action.
 *
 * Rules (tests/Feature/TradingControlTest.php):
 *  - the kill switch starts ENGAGED on a fresh install;
 *  - stopping is always allowed and idempotent; it blocks new trades and
 *    NEVER closes positions — closing is a separate, deliberate action;
 *  - the operating mode can only change while trading is stopped;
 *  - LIVE mode needs the server lock off (LIVE_TRADING_ENABLED=true), MFA,
 *    the user's password and a typed confirmation phrase;
 *  - every attempt, allowed or refused, is audited.
 */
class TradingControl
{
    public function __construct(
        private readonly AuditLogger $audit,
        private readonly Notifier $notifier,
        private readonly EngineClient $engine,
    ) {}

    public function liveLocked(): bool
    {
        return ! config('fx.live_trading_enabled');
    }

    public function status(): TradingStatus
    {
        $state = SystemState::current();
        [$engine, $detail] = $this->engineState($state);

        return new TradingStatus($state, $this->liveLocked(), $engine, $detail);
    }

    /** @return array{0: EngineState, 1: string} */
    public function engineState(SystemState $state): array
    {
        $beat = $state->engine_heartbeat_at;
        $fresh = (int) config('fx.engine.heartbeat_freshness_seconds', 30);
        if ($beat === null) {
            return [EngineState::Offline, 'The trading engine has not started yet. Start it with "make dev".'];
        }
        if ($beat->lt(now()->subSeconds($fresh))) {
            return [EngineState::Offline, 'No engine heartbeat since '.$beat->format('Y-m-d H:i:s').' UTC.'];
        }
        if ($state->engine_degraded) {
            return [EngineState::Degraded, $state->engine_detail ?: 'Some accounts have problems.'];
        }

        return [EngineState::Running, $state->engine_detail ?: 'Running.'];
    }

    public function stop(User $actor, string $reason): SystemState
    {
        $already = false;
        $state = DB::transaction(function () use ($actor, $reason, &$already) {
            $state = SystemState::query()->lockForUpdate()->findOrFail(1);
            $already = $state->kill_switch_engaged;
            if (! $already) {
                $state->fill([
                    'kill_switch_engaged' => true,
                    'kill_switch_reason' => mb_substr($reason, 0, 500),
                    'kill_switch_changed_at' => now(),
                    'kill_switch_changed_by' => $actor->id,
                ])->save();
            }
            $this->audit->record('trading.kill_switch.engaged', actor: $actor, targetType: 'system',
                details: ['reason' => $reason, 'already_engaged' => $already]);

            return $state;
        });
        if (! $already) {
            $this->notifier->notify('trading.stopped', "All new trading stopped by {$actor->email}: {$reason}. Open positions were NOT closed.");
        }

        return $state;
    }

    public function resume(User $actor): SystemState
    {
        $resumed = false;
        $refusal = null;
        $state = DB::transaction(function () use ($actor, &$resumed, &$refusal) {
            $state = SystemState::query()->lockForUpdate()->findOrFail(1);
            if (! $state->kill_switch_engaged) {
                return $state;
            }
            if ($state->trading_mode === TradingMode::Live && $this->liveLocked()) {
                $refusal = new DomainException('LIVE trading is locked on this server (LIVE_TRADING_ENABLED=false).', 403, 'live_locked');

                return $state;
            }
            $state->fill([
                'kill_switch_engaged' => false,
                'kill_switch_reason' => null,
                'kill_switch_changed_at' => now(),
                'kill_switch_changed_by' => $actor->id,
            ])->save();
            $resumed = true;
            $this->audit->record('trading.kill_switch.released', actor: $actor, targetType: 'system',
                details: ['mode' => $state->trading_mode->value]);

            return $state;
        });
        if ($refusal !== null) { // audited outside the transaction so the record is kept
            $this->audit->record('trading.kill_switch.release_denied', AuditOutcome::Denied, $actor, 'system',
                details: ['reason' => $refusal->errorCode]);
            throw $refusal;
        }
        if ($resumed) {
            $this->notifier->notify('trading.resumed', "Trading resumed by {$actor->email} in {$state->trading_mode->value} mode.");
        }

        return $state;
    }

    public function setMode(User $actor, TradingMode $mode, ?string $password = null, ?string $phrase = null): SystemState
    {
        $refusal = null;
        $previous = null;
        $state = DB::transaction(function () use ($actor, $mode, $password, $phrase, &$refusal, &$previous) {
            $state = SystemState::query()->lockForUpdate()->findOrFail(1);
            $previous = $state->trading_mode;
            if ($mode === $previous) {
                return $state;
            }
            $refusal = $this->modeRefusal($state, $actor, $mode, $password, $phrase);
            if ($refusal !== null) {
                return $state;
            }
            $state->fill(['trading_mode' => $mode, 'mode_changed_at' => now(), 'mode_changed_by' => $actor->id])->save();
            $this->audit->record($mode === TradingMode::Live ? 'trading.mode.live_enabled' : 'trading.mode.changed',
                actor: $actor, targetType: 'system', details: ['from' => $previous->value, 'to' => $mode->value]);

            return $state;
        });
        if ($refusal !== null) { // audited outside the transaction so the record is kept
            $this->audit->record('trading.mode.change_denied', AuditOutcome::Denied, $actor, 'system',
                details: ['from' => $previous?->value, 'to' => $mode->value, 'reason' => $refusal->getMessage()]);
            throw $refusal;
        }

        return $state;
    }

    private function modeRefusal(SystemState $state, User $actor, TradingMode $mode, ?string $password, ?string $phrase): ?DomainException
    {
        if (! $state->kill_switch_engaged) {
            return new DomainException('Stop all trading before changing the operating mode.', 409, 'stop_first');
        }
        if ($mode !== TradingMode::Live) {
            return null;
        }
        if ($this->liveLocked()) {
            return new DomainException('LIVE trading is locked on this server (LIVE_TRADING_ENABLED=false).', 403, 'live_locked');
        }
        if (! $actor->hasMfa()) {
            return new DomainException('Turn on two-factor authentication before enabling LIVE trading.', 403, 'mfa_required');
        }
        if (! $password || ! Hash::check($password, $actor->password)) {
            return new DomainException('Password confirmation failed.', 403, 'password_incorrect');
        }
        if (trim((string) $phrase) !== config('fx.live_confirmation_phrase')) {
            return new DomainException('Type "'.config('fx.live_confirmation_phrase').'" to confirm.', 403, 'confirmation_required');
        }

        return null;
    }

    /**
     * The separate, deliberate "Close positions" action. It always stops new
     * trading first, then asks the engine to close every open position.
     */
    public function closeAllPositions(User $actor, string $reason): array
    {
        $this->stop($actor, "EMERGENCY: {$reason}");
        $result = $this->engine->post('/internal/positions/close-all', ['actor_label' => $actor->email], 120);
        $failed = $result['failed'] ?? [];
        $this->audit->record('trading.close_all_positions', $failed ? AuditOutcome::Failure : AuditOutcome::Success,
            $actor, 'system', details: ['reason' => $reason, 'closed' => $result['closed'] ?? 0, 'failed' => count($failed)]);

        return $result;
    }
}
