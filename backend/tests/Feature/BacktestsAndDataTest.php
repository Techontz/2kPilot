<?php

namespace Tests\Feature;

use App\Jobs\RunBacktest;
use App\Models\Backtest;
use App\Models\Dataset;
use App\Services\Engine\EngineClient;
use App\Services\Notifier;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Queue;
use Illuminate\Support\Str;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class BacktestsAndDataTest extends TestCase
{
    use CreatesTradingData;

    private function dataset(): Dataset
    {
        return Dataset::query()->create(['symbol' => 'EURUSD', 'timeframe' => 'H1', 'source' => 'synthetic', 'source_ref' => 'seed-1', 'description' => 'SYNTHETIC']);
    }

    private function backtestRow(string $status = 'QUEUED'): Backtest
    {
        return Backtest::query()->create([
            'id' => (string) Str::uuid(), 'kind' => 'SINGLE', 'status' => $status, 'strategy_key' => 'trend_pullback', 'code_version' => '1.0.0',
            'parameters' => [], 'symbol' => 'EURUSD', 'timeframe' => 'H1', 'data_source' => 'synthetic',
            'start' => now()->subMonths(3), 'end' => now(), 'initial_capital' => '10000', 'account_currency' => 'USD',
            'risk_settings' => [], 'costs' => [], 'config' => [],
        ]);
    }

    public function test_starting_a_backtest_creates_it_on_the_engine_and_queues_the_run(): void
    {
        Queue::fake();
        $version = $this->strategyVersion();
        $dataset = $this->dataset();
        $row = $this->backtestRow();
        $this->fakeEngine(['/internal/backtests' => ['id' => $row->id, 'status' => 'QUEUED']]);
        $this->actingAs($this->owner())->postJson('/api/backtests', [
            'mode' => 'single', 'strategy_version_id' => $version->id, 'dataset_id' => $dataset->id,
            'start' => '2026-01-01', 'end' => '2026-06-01', 'initial_capital' => 10000,
            'costs' => ['spread_pips' => 1.2, 'commission_per_lot' => 3.5, 'slippage_pips' => 0.2],
        ])->assertStatus(202)->assertJsonPath('id', $row->id);
        Http::assertSent(fn (Request $r) => $r['strategy_key'] === 'trend_pullback' && $r['parameters']['ema_fast'] === 50 && $r['costs']['spread_pips'] === 1.2);
        Queue::assertPushed(RunBacktest::class, fn ($job) => $job->backtestId === $row->id);
    }

    public function test_backtest_requests_are_validated(): void
    {
        Http::fake();
        $this->actingAs($this->owner())->postJson('/api/backtests', ['mode' => 'yolo'])->assertStatus(422)
            ->assertJsonValidationErrors(['mode', 'strategy_version_id', 'dataset_id', 'start', 'end', 'initial_capital']);
        Http::assertNothingSent();
    }

    public function test_job_marks_the_backtest_failed_when_the_engine_is_down(): void
    {
        $row = $this->backtestRow();
        $this->engineDown();
        (new RunBacktest($row->id))->handle(app(EngineClient::class), app(Notifier::class));
        $this->assertSame('FAILED', $row->fresh()->status->value);
        $this->assertDatabaseHas('notifications', ['type' => 'backtest.failed']);
    }

    public function test_running_backtests_cannot_be_deleted(): void
    {
        $row = $this->backtestRow('RUNNING');
        $this->actingAs($this->owner())->deleteJson("/api/backtests/{$row->id}")->assertStatus(409);
        $row->update(['status' => 'COMPLETED']);
        $this->deleteJson("/api/backtests/{$row->id}")->assertOk();
    }

    public function test_synthetic_data_is_generated_by_the_engine(): void
    {
        $dataset = $this->dataset();
        $this->fakeEngine(['/internal/datasets/synthetic' => ['id' => $dataset->id, 'bars' => 2000]]);
        $this->actingAs($this->owner())->postJson('/api/datasets/synthetic', ['symbol' => 'EURUSD', 'timeframe' => 'H1', 'days' => 365])
            ->assertCreated()->assertJsonPath('source', 'synthetic');
        $this->assertDatabaseHas('audit_logs', ['action' => 'data.synthetic_generated']);
    }
}
