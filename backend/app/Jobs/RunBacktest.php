<?php

namespace App\Jobs;

use App\Enums\BacktestStatus;
use App\Models\Backtest;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use App\Services\Notifier;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;

/**
 * Runs a queued backtest on the trading engine (where the strategy, risk and
 * cost models live). Backtests can take minutes, so they never block a request.
 *
 * Queue "backtests" on the "redis-long" connection (retry_after above the
 * timeout), processed by Horizon's backtests supervisor.
 */
class RunBacktest implements ShouldQueue
{
    use Queueable;

    public int $timeout = 1800;

    public int $tries = 1; // a backtest is deterministic: a failure is reported, not retried

    public function __construct(public readonly string $backtestId)
    {
        $this->onQueue('backtests');
        if (config('queue.default') === 'redis') {
            $this->onConnection('redis-long');
        }
    }

    public function handle(EngineClient $engine, Notifier $notifier): void
    {
        try {
            $engine->post("/internal/backtests/{$this->backtestId}/run", [], $this->timeout - 30);
        } catch (EngineException $e) {
            $backtest = Backtest::query()->find($this->backtestId);
            if ($backtest && in_array($backtest->status, [BacktestStatus::Queued, BacktestStatus::Running], true)) {
                $backtest->forceFill(['status' => BacktestStatus::Failed, 'error' => $e->getMessage(), 'finished_at' => now()])->save();
                $notifier->notify('backtest.failed', "{$backtest->name}: {$e->getMessage()}", $backtest->user_id, data: ['backtest_id' => $backtest->id]);
            }
        }
    }
}
