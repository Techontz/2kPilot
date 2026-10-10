<?php

namespace App\Console\Commands;

use App\Enums\EngineState;
use App\Models\SystemState;
use App\Services\Notifier;
use App\Services\Trading\TradingControl;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Cache;

/**
 * Scheduled every minute. If the trading engine stops writing heartbeats it
 * cannot warn anyone itself — so Laravel does, once per outage.
 */
class EngineWatchdog extends Command
{
    protected $signature = 'tp:engine-watchdog';

    protected $description = 'Notify when the trading engine goes offline or comes back';

    public function handle(TradingControl $control, Notifier $notifier): int
    {
        $state = SystemState::current();
        [$engine, $detail] = $control->engineState($state);
        $wasOffline = Cache::get('tp.engine_offline', false);
        if ($engine === EngineState::Offline && ! $wasOffline && $state->engine_heartbeat_at !== null) {
            $notifier->notify('system.engine_offline', "The trading engine stopped responding. {$detail} No automated trading happens until it is back.", null);
            Cache::forever('tp.engine_offline', true);
            $this->warn('engine offline — notified');
        } elseif ($engine !== EngineState::Offline && $wasOffline) {
            $notifier->notify('system.engine_online', 'The trading engine is running again.', null);
            Cache::forget('tp.engine_offline');
            $this->info('engine back online — notified');
        }

        return self::SUCCESS;
    }
}
