<?php

namespace App\Services\Trading;

use App\Enums\EngineState;
use App\Enums\TradingMode;
use App\Models\SystemState;

/** A snapshot of the global controls, answering "may anything open a trade now?". */
final class TradingStatus
{
    public function __construct(
        public readonly SystemState $state,
        public readonly bool $liveLocked,
        public readonly EngineState $engine,
        public readonly string $engineDetail,
    ) {}

    public function newOrdersPermitted(): bool
    {
        if ($this->state->kill_switch_engaged) {
            return false;
        }
        if ($this->state->trading_mode === TradingMode::Live && $this->liveLocked) {
            return false;
        }
        if ($this->engine === EngineState::Offline) {
            return false;
        }

        return $this->state->trading_mode !== TradingMode::Backtest;
    }

    public function toArray(): array
    {
        $s = $this->state;

        return [
            'trading_mode' => $s->trading_mode->value,
            'kill_switch_engaged' => $s->kill_switch_engaged,
            'kill_switch_reason' => $s->kill_switch_reason,
            'kill_switch_changed_at' => $s->kill_switch_changed_at?->toIso8601String(),
            'live_trading_locked' => $this->liveLocked,
            'engine_state' => $this->engine->value,
            'engine_detail' => $this->engineDetail,
            'engine_heartbeat_at' => $s->engine_heartbeat_at?->toIso8601String(),
            'new_orders_permitted' => $this->newOrdersPermitted(),
        ];
    }
}
