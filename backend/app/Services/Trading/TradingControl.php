<?php

namespace App\Services\Trading;

use App\Enums\AccountEnvironment;
use App\Enums\AuditOutcome;
use App\Enums\EngineState;
use App\Enums\TradingMode;
use App\Exceptions\DomainException;
use App\Models\SystemState;
use App\Models\TradingAccount;
use App\Models\User;
use App\Models\UserTradingState;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use App\Services\Mfa\TwoFactorService;
use App\Services\Notifier;
use App\Services\Users\UserProvisioner;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Hash;

/**
 * Trading controls.
 *
 * Per user (user_trading_states): STOP TRADING (kill switch), resume, the
 * operating mode and the separate "Close positions" emergency action. They
 * act on the current user's own accounts only.
 *
 * Platform (system_state, admins only): the emergency HALT, which stops every
 * user's trading at once without touching anyone's own switch.
 *
 * Rules (tests/Feature/TradingControlTest.php):
 *  - a new user starts STOPPED in DEMO mode;
 *  - stopping is always allowed and idempotent; it blocks new trades and
 *    NEVER closes positions — closing is a separate, deliberate action;
 *  - the operating mode can only change while the user's trading is stopped;
 *  - LIVE mode needs the server lock off (LIVE_TRADING_ENABLED=true), MFA
 *    plus a fresh two-factor code, the user's password, a typed confirmation phrase and one of the user's
 *    LIVE accounts with a risk profile: the authorisation time, that account
 *    and profile, and a snapshot of the profile's limits are recorded;
 *  - LIVE authorisation covers exactly that account and profile as they were:
 *    editing the profile, changing the account's profile, re-enabling the
 *    account's trading, adding another LIVE account, turning MFA off or
 *    changing the password REVOKES it (back to DEMO, trading stopped);
 *  - starting trades in LIVE mode needs `live: true` from the client, so a
 *    dialog that still said "Demo" can never start real-money trading;
 *  - every attempt, allowed or refused, is audited.
 */
class TradingControl
{
    private const NO_LIVE_AUTHORIZATION = [
        'live_authorized_at' => null,
        'live_authorized_limits' => null,
        'live_authorized_account_id' => null,
        'live_authorized_profile_id' => null,
    ];

    public function __construct(
        private readonly AuditLogger $audit,
        private readonly Notifier $notifier,
        private readonly EngineClient $engine,
        private readonly UserProvisioner $provisioner,
        private readonly TwoFactorService $mfa,
    ) {}

    public function liveLocked(): bool
    {
        return ! config('tradepilot.live_trading_enabled');
    }

    public function stateOf(User $user): UserTradingState
    {
        $state = UserTradingState::query()->find($user->id);
        if ($state === null) { // users created before provisioning existed, or by hand
            $this->provisioner->provision($user);
            $state = UserTradingState::query()->findOrFail($user->id);
        }

        return $state;
    }

    public function status(User $user): TradingStatus
    {
        $platform = SystemState::current();
        [$engine, $detail] = $this->engineState($platform);

        return new TradingStatus($this->stateOf($user), $platform, $this->liveLocked(), $engine, $detail);
    }

    /** @return array{0: EngineState, 1: string} */
    public function engineState(SystemState $state): array
    {
        $beat = $state->engine_heartbeat_at;
        $fresh = (int) config('tradepilot.engine.heartbeat_freshness_seconds', 30);
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

    public function stop(User $actor, string $reason): UserTradingState
    {
        $this->stateOf($actor);
        $already = false;
        $state = DB::transaction(function () use ($actor, $reason, &$already) {
            $state = UserTradingState::query()->lockForUpdate()->findOrFail($actor->id);
            $already = $state->kill_switch_engaged;
            if (! $already) {
                $state->fill([
                    'kill_switch_engaged' => true,
                    'kill_switch_reason' => mb_substr($reason, 0, 500),
                    'kill_switch_changed_at' => now(),
                ])->save();
            }
            $this->audit->record('trading.kill_switch.engaged', actor: $actor, targetType: 'user_trading_state', targetId: $actor->id,
                details: ['reason' => $reason, 'already_engaged' => $already]);

            return $state;
        });
        if (! $already) {
            $this->notifier->notify('trading.stopped', "Your new trading was stopped: {$reason}. Open positions were NOT closed.", $actor->id);
        }

        return $state;
    }

    /** @param  bool  $liveConfirmed  the user confirmed starting in LIVE (real-money) mode */
    public function resume(User $actor, bool $liveConfirmed = false): UserTradingState
    {
        $this->stateOf($actor);
        $resumed = false;
        $refusal = null;
        $state = DB::transaction(function () use ($actor, $liveConfirmed, &$resumed, &$refusal) {
            $state = UserTradingState::query()->lockForUpdate()->findOrFail($actor->id);
            if (! $state->kill_switch_engaged) {
                return $state;
            }
            if ($state->trading_mode === TradingMode::Live && $this->liveLocked()) {
                $refusal = new DomainException('LIVE trading is locked on this server (LIVE_TRADING_ENABLED=false).', 403, 'live_locked');

                return $state;
            }
            if ($state->trading_mode === TradingMode::Live && $state->live_authorized_at === null) {
                $refusal = new DomainException('Switch to LIVE mode again to authorise real-money trading.', 403, 'live_not_authorized');

                return $state;
            }
            if ($state->trading_mode === TradingMode::Live && ! $liveConfirmed) {
                $refusal = new DomainException('Your trading is in LIVE (real-money) mode. Confirm starting LIVE trading.', 409, 'live_confirmation_required');

                return $state;
            }
            $state->fill([
                'kill_switch_engaged' => false,
                'kill_switch_reason' => null,
                'kill_switch_changed_at' => now(),
            ])->save();
            $resumed = true;
            $this->audit->record('trading.kill_switch.released', actor: $actor, targetType: 'user_trading_state', targetId: $actor->id,
                details: ['mode' => $state->trading_mode->value]);

            return $state;
        });
        if ($refusal !== null) { // audited outside the transaction so the record is kept
            $this->audit->record('trading.kill_switch.release_denied', AuditOutcome::Denied, $actor, 'user_trading_state', $actor->id,
                details: ['reason' => $refusal->errorCode]);
            throw $refusal;
        }
        if ($resumed) {
            $this->notifier->notify('trading.resumed', "Trading resumed in {$state->trading_mode->value} mode.", $actor->id);
        }

        return $state;
    }

    public function setMode(User $actor, TradingMode $mode, ?string $password = null, ?string $phrase = null, ?string $accountId = null, ?string $mfaCode = null): UserTradingState
    {
        $this->stateOf($actor);
        $refusal = null;
        $previous = null;
        $state = DB::transaction(function () use ($actor, $mode, $password, $phrase, $accountId, $mfaCode, &$refusal, &$previous) {
            $state = UserTradingState::query()->lockForUpdate()->findOrFail($actor->id);
            $previous = $state->trading_mode;
            if ($mode === $previous) {
                return $state;
            }
            $account = $accountId !== null ? TradingAccount::query()->ownedBy($actor)->with('riskProfile')->find($accountId) : null;
            $refusal = $this->modeRefusal($state, $actor, $mode, $password, $phrase, $account, $mfaCode);
            if ($refusal !== null) {
                return $state;
            }
            $state->fill(['trading_mode' => $mode, 'mode_changed_at' => now()]);
            $state->fill($mode === TradingMode::Live
                ? ['live_authorized_at' => now(), 'live_authorized_limits' => $this->limitsSnapshot($account),
                    'live_authorized_account_id' => $account->id, 'live_authorized_profile_id' => $account->risk_profile_id,
                    'live_revoked_reason' => null, 'live_revoked_at' => null]
                : self::NO_LIVE_AUTHORIZATION);
            $state->save();
            $this->audit->record($mode === TradingMode::Live ? 'trading.mode.live_enabled' : 'trading.mode.changed',
                actor: $actor, targetType: 'user_trading_state', targetId: $actor->id,
                details: ['from' => $previous->value, 'to' => $mode->value, 'account_id' => $account?->id]);

            return $state;
        });
        if ($refusal !== null) { // audited outside the transaction so the record is kept
            $this->audit->record('trading.mode.change_denied', AuditOutcome::Denied, $actor, 'user_trading_state', $actor->id,
                details: ['from' => $previous?->value, 'to' => $mode->value, 'reason' => $refusal->getMessage()]);
            throw $refusal;
        }

        return $state;
    }

    private function modeRefusal(UserTradingState $state, User $actor, TradingMode $mode, ?string $password, ?string $phrase, ?TradingAccount $account, ?string $mfaCode = null): ?DomainException
    {
        if (! $state->kill_switch_engaged) {
            return new DomainException('Stop your trading before changing the operating mode.', 409, 'stop_first');
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
        if ($mfaCode === null || trim($mfaCode) === '' || ! $this->mfa->verify($actor, $mfaCode)) {
            return new DomainException('That two-factor code is not valid.', 403, 'mfa_code_invalid');
        }
        if (! $password || ! Hash::check($password, $actor->password)) {
            return new DomainException('Password confirmation failed.', 403, 'password_incorrect');
        }
        $required = config('tradepilot.live_confirmation_phrase');
        if (trim((string) $phrase) !== $required) {
            return new DomainException('Type "'.$required.'" to confirm.', 403, 'confirmation_required');
        }
        if ($account === null || $account->environment !== AccountEnvironment::Live) {
            return new DomainException('Choose one of your LIVE accounts to authorise.', 422, 'live_account_required');
        }
        if ($account->riskProfile === null) {
            return new DomainException('Assign a risk profile to that account before enabling LIVE trading.', 422, 'risk_profile_required');
        }

        return null;
    }

    /** The risk limits the user saw when authorising LIVE, kept for the record. */
    private function limitsSnapshot(TradingAccount $account): array
    {
        $profile = $account->riskProfile;

        return [
            'account_id' => $account->id,
            'account_label' => $account->label,
            'risk_profile_id' => $profile->id,
            'risk_profile_name' => $profile->name,
            'limits' => $profile->only(array_keys(UserProvisioner::BEGINNER_LIMITS)),
            'account_trading_enabled' => $account->trading_enabled,
            'captured_at' => now()->toIso8601String(),
        ];
    }

    /**
     * Take real-money authorisation away from the owner of `$ownerId` when
     * `$applies` says the change touches it: back to DEMO, the user's trading
     * stopped, authorisation cleared, the reason kept for the dashboard.
     * Returns whether anything was revoked.
     *
     * @param  callable(UserTradingState): bool  $applies
     */
    public function revokeLiveIf(string $ownerId, User $actor, string $because, callable $applies): bool
    {
        $owner = $actor->id === $ownerId ? $actor : User::query()->find($ownerId);
        if ($owner === null) {
            return false;
        }
        $this->stateOf($owner);
        $reason = "Real-money authorization was revoked because {$because}.";
        $revoked = DB::transaction(function () use ($ownerId, $actor, $reason, $applies) {
            $state = UserTradingState::query()->lockForUpdate()->findOrFail($ownerId);
            if (($state->trading_mode !== TradingMode::Live && $state->live_authorized_at === null) || ! $applies($state)) {
                return false;
            }
            $from = $state->trading_mode;
            $state->fill(self::NO_LIVE_AUTHORIZATION + [
                'trading_mode' => TradingMode::Demo,
                'mode_changed_at' => now(),
                'live_revoked_reason' => $reason,
                'live_revoked_at' => now(),
            ]);
            if (! $state->kill_switch_engaged) {
                $state->fill(['kill_switch_engaged' => true, 'kill_switch_reason' => mb_substr($reason, 0, 500), 'kill_switch_changed_at' => now()]);
            }
            $state->save();
            $this->audit->record('trading.mode.live_revoked', actor: $actor, targetType: 'user_trading_state', targetId: $ownerId,
                details: ['from' => $from->value, 'to' => TradingMode::Demo->value, 'reason' => $reason]);

            return true;
        });
        if ($revoked) {
            $this->notifier->notify('trading.live_revoked', "{$reason} Your trading was stopped and switched to DEMO; open positions were NOT closed.", $ownerId);
        }

        return $revoked;
    }

    /**
     * "Trading enabled" was switched on for an account. The first time after
     * LIVE authorisation of an account that was off then is expected; turning
     * the authorised account back on after it was switched off revokes LIVE.
     */
    public function accountTradingEnabled(TradingAccount $account, User $actor): void
    {
        $state = UserTradingState::query()->find($account->user_id);
        if ($state === null || $state->live_authorized_account_id !== $account->id) {
            return;
        }
        if (($state->live_authorized_limits['account_trading_enabled'] ?? true) === false) {
            $state->live_authorized_limits = ['account_trading_enabled' => true] + $state->live_authorized_limits;
            $state->save();

            return;
        }
        $this->revokeLiveIf($account->user_id, $actor, "trading on \"{$account->label}\" was switched off and on again",
            fn (UserTradingState $s) => $s->live_authorized_account_id === $account->id);
    }

    /**
     * The separate, deliberate "Close positions" action for the user's own
     * accounts. It always stops the user's new trading first.
     */
    public function closeAllPositions(User $actor, string $reason): array
    {
        $this->stop($actor, "EMERGENCY: {$reason}");
        $accountIds = TradingAccount::query()->ownedBy($actor)->pluck('id')->all();
        $result = $this->engine->post('/internal/positions/close-all', ['account_ids' => $accountIds, 'actor_label' => $actor->email], 120);
        $failed = $result['failed'] ?? [];
        $this->audit->record('trading.close_all_positions', $failed ? AuditOutcome::Failure : AuditOutcome::Success,
            $actor, 'user_trading_state', $actor->id, details: ['reason' => $reason, 'closed' => $result['closed'] ?? 0, 'failed' => count($failed)]);

        return $result;
    }

    /** Admin: stop every user's trading at once. Users' own switches are not changed. */
    public function haltPlatform(User $admin, string $reason): SystemState
    {
        $already = false;
        $state = DB::transaction(function () use ($admin, $reason, &$already) {
            $state = SystemState::query()->lockForUpdate()->findOrFail(1);
            $already = $state->kill_switch_engaged;
            if (! $already) {
                $state->fill([
                    'kill_switch_engaged' => true,
                    'kill_switch_reason' => mb_substr($reason, 0, 500),
                    'kill_switch_changed_at' => now(),
                    'kill_switch_changed_by' => $admin->id,
                ])->save();
            }
            $this->audit->record('platform.halt.engaged', actor: $admin, targetType: 'system',
                details: ['reason' => $reason, 'already_engaged' => $already]);

            return $state;
        });
        if (! $already) {
            $this->notifier->notify('platform.halted', "Platform halted by {$admin->email}: {$reason}. No user can open trades.", null);
        }

        return $state;
    }

    public function resumePlatform(User $admin): SystemState
    {
        $released = false;
        $state = DB::transaction(function () use ($admin, &$released) {
            $state = SystemState::query()->lockForUpdate()->findOrFail(1);
            if ($state->kill_switch_engaged) {
                $state->fill([
                    'kill_switch_engaged' => false,
                    'kill_switch_reason' => null,
                    'kill_switch_changed_at' => now(),
                    'kill_switch_changed_by' => $admin->id,
                ])->save();
                $released = true;
                $this->audit->record('platform.halt.released', actor: $admin, targetType: 'system');
            }

            return $state;
        });
        if ($released) {
            $this->notifier->notify('platform.resumed', "Platform halt lifted by {$admin->email}. Each user's own STOP switch still applies.", null);
        }

        return $state;
    }
}
