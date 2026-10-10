<?php

namespace App\Services\Trading;

use App\Enums\EngineState;
use App\Enums\TradingMode;
use App\Models\SystemState;
use App\Models\UserTradingState;

/**
 * A snapshot of one user's controls plus the platform's, answering "may
 * anything open a trade on this user's accounts now?".
 */
final class TradingStatus
{
    public function __construct(
        public readonly UserTradingState $user,
        public readonly SystemState $platform,
        public readonly bool $liveLocked,
        public readonly EngineState $engine,
        public readonly string $engineDetail,
    ) {}

    public function newOrdersPermitted(): bool
    {
        if ($this->platform->kill_switch_engaged || $this->user->kill_switch_engaged) {
            return false;
        }
        if ($this->user->trading_mode === TradingMode::Live && ($this->liveLocked || $this->user->live_authorized_at === null)) {
            return false;
        }

        return $this->engine !== EngineState::Offline;
    }

    public function toArray(): array
    {
        $u = $this->user;
        $p = $this->platform;

        return [
            'trading_mode' => $u->trading_mode->value,
            'kill_switch_engaged' => $u->kill_switch_engaged,
            'kill_switch_reason' => $u->kill_switch_reason,
            'kill_switch_changed_at' => $u->kill_switch_changed_at?->toIso8601String(),
            'live_trading_locked' => $this->liveLocked,
            'live_authorized_at' => $u->live_authorized_at?->toIso8601String(),
            'live_authorized_account_id' => $u->live_authorized_account_id,
            'live_revoked_reason' => $u->live_revoked_reason,
            'live_revoked_at' => $u->live_revoked_at?->toIso8601String(),
            'live_confirmation_phrase' => config('tradepilot.live_confirmation_phrase'),
            'platform_halted' => $p->kill_switch_engaged,
            'platform_halt_reason' => $p->kill_switch_engaged ? $p->kill_switch_reason : null,
            'engine_state' => $this->engine->value,
            'engine_detail' => $this->engineDetail,
            'engine_heartbeat_at' => $p->engine_heartbeat_at?->toIso8601String(),
            'new_orders_permitted' => $this->newOrdersPermitted(),
        ];
    }
}
