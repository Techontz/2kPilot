<?php

namespace Tests\Feature;

use App\Enums\ConnectorType;
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
            'id' => (string) Str::uuid(), 'user_id' => $this->me()->id, 'kind' => 'SINGLE', 'status' => $status, 'strategy_key' => 'trend_pullback', 'code_version' => '1.0.0',
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
        $this->actingAs($this->me())->postJson('/api/backtests', [
            'mode' => 'single', 'strategy_version_id' => $version->id, 'dataset_id' => $dataset->id,
            'start' => '2026-01-01', 'end' => '2026-06-01', 'initial_capital' => 10000,
            'costs' => ['spread_pips' => 1.2, 'commission_per_lot' => 3.5, 'slippage_pips' => 0.2],
        ])->assertStatus(202)->assertJsonPath('id', $row->id);
        Http::assertSent(fn (Request $r) => $r['strategy_key'] === 'trend_pullback' && $r['parameters']['ema_fast'] === 50 && $r['costs']['spread_pips'] === 1.2);
        Queue::assertPushed(RunBacktest::class, fn ($job) => $job->backtestId === $row->id && $job->queue === 'backtests');
    }

    public function test_rule_parameters_keep_empty_objects_when_forwarded_to_the_engine(): void
    {
        Queue::fake();
        $version = $this->strategyVersion();
        $version->forceFill(['parameters' => ['entry' => ['buy' => ['all' => [['left' => ['price' => 'close', 'params' => new \stdClass], 'op' => 'gt', 'right' => ['value' => 1]]]]]]])->save();
        $dataset = $this->dataset();
        $row = $this->backtestRow();
        $this->fakeEngine(['/internal/backtests' => ['id' => $row->id, 'status' => 'QUEUED']]);
        $this->actingAs($this->me())->postJson('/api/backtests', [
            'mode' => 'single', 'strategy_version_id' => $version->id, 'dataset_id' => $dataset->id,
            'start' => '2026-01-01', 'end' => '2026-06-01', 'initial_capital' => 1000,
        ])->assertStatus(202);
        Http::assertSent(fn (Request $r) => str_contains($r->body(), '"params":{}'));
    }

    public function test_contract_backtests_forward_the_contract_and_payout_settings(): void
    {
        Queue::fake();
        $version = $this->strategyVersion();
        $dataset = $this->dataset();
        $row = $this->backtestRow();
        $row->update(['config' => ['contract' => ['contract_family' => 'RISE_FALL'], 'payout_ratio' => '0.9']]);
        $this->fakeEngine(['/internal/backtests' => ['id' => $row->id, 'status' => 'QUEUED']]);
        $base = ['mode' => 'single', 'strategy_version_id' => $version->id, 'dataset_id' => $dataset->id, 'start' => '2026-01-01', 'end' => '2026-06-01', 'initial_capital' => 1000];
        $this->actingAs($this->me())->postJson('/api/backtests', $base + [
            'contract' => ['contract_family' => 'RISE_FALL', 'duration' => 15, 'duration_unit' => 'm', 'stake' => 2], 'payout_ratio' => 0.9, 'commission_pct' => 1.5,
        ])->assertStatus(202);
        Http::assertSent(fn (Request $r) => $r['contract'] === ['contract_family' => 'RISE_FALL', 'duration' => 15, 'duration_unit' => 'm', 'allow_equals' => false,
            'stake' => '2.00', 'multiplier' => null, 'take_profit_amount' => null, 'stop_loss_amount' => null]
            && $r['payout_ratio'] === '0.9' && $r['commission_pct'] === '1.5');
        $this->getJson('/api/backtests')->assertOk()->assertJsonPath('0.config.payout_ratio', '0.9');

        // Without a contract: SPOT (no Deriv default), default payout and commission.
        Http::fake(['engine.test/internal/backtests*' => Http::response(['id' => $row->id, 'status' => 'QUEUED'])]);
        $this->postJson('/api/backtests', $base)->assertStatus(202);
        Http::assertSent(fn (Request $r) => ! isset($r['contract']) && $r['payout_ratio'] === '0.95' && $r['commission_pct'] === '0');
    }

    public function test_backtest_contracts_are_validated(): void
    {
        Http::fake();
        $base = ['mode' => 'single', 'strategy_version_id' => $this->strategyVersion()->id, 'dataset_id' => $this->dataset()->id, 'start' => '2026-01-01', 'end' => '2026-06-01', 'initial_capital' => 1000];
        $this->actingAs($this->me())->postJson('/api/backtests', $base + ['contract' => ['contract_family' => 'RISE_FALL']])
            ->assertJsonValidationErrors(['contract.duration', 'contract.duration_unit']);
        $this->postJson('/api/backtests', $base + ['contract' => ['contract_family' => 'MULTIPLIER', 'multiplier' => 10, 'duration' => 5]])->assertJsonValidationErrors('contract.duration');
        $this->postJson('/api/backtests', $base + ['payout_ratio' => 3, 'commission_pct' => 11])->assertJsonValidationErrors(['payout_ratio', 'commission_pct']);
        Http::assertNothingSent();
    }

    public function test_backtest_requests_are_validated(): void
    {
        Http::fake();
        $this->actingAs($this->me())->postJson('/api/backtests', ['mode' => 'yolo'])->assertStatus(422)
            ->assertJsonValidationErrors(['mode', 'strategy_version_id', 'dataset_id', 'start', 'end', 'initial_capital']);
        Http::assertNothingSent();
    }

    public function test_job_marks_the_backtest_failed_when_the_engine_is_down(): void
    {
        $row = $this->backtestRow();
        $this->engineDown();
        (new RunBacktest($row->id))->handle(app(EngineClient::class), app(Notifier::class));
        $this->assertSame('FAILED', $row->fresh()->status->value);
        $this->assertDatabaseHas('notifications', ['type' => 'backtest.failed', 'user_id' => $this->me()->id]);
    }

    public function test_running_backtests_cannot_be_deleted(): void
    {
        $row = $this->backtestRow('RUNNING');
        $this->actingAs($this->me())->deleteJson("/api/backtests/{$row->id}")->assertStatus(409);
        $row->update(['status' => 'COMPLETED']);
        $this->deleteJson("/api/backtests/{$row->id}")->assertOk();
    }

    public function test_synthetic_data_is_generated_by_the_engine(): void
    {
        $dataset = $this->dataset();
        $this->fakeEngine(['/internal/datasets/synthetic' => ['id' => $dataset->id, 'bars' => 2000]]);
        $this->actingAs($this->me())->postJson('/api/datasets/synthetic', ['symbol' => 'EURUSD', 'timeframe' => 'H1', 'days' => 365])
            ->assertCreated()->assertJsonPath('source', 'synthetic');
        $this->assertDatabaseHas('audit_logs', ['action' => 'data.synthetic_generated']);
        Http::assertSent(fn (Request $r) => $r['user_id'] === $this->me()->id);
    }

    public function test_practice_data_on_short_candles_has_a_capped_period(): void
    {
        $dataset = $this->dataset();
        $this->fakeEngine(['/internal/datasets/synthetic' => ['id' => $dataset->id, 'bars' => 8000]]);
        $this->actingAs($this->me());
        $this->postJson('/api/datasets/synthetic', ['symbol' => 'R_75', 'timeframe' => 'M5', 'days' => 365])->assertCreated();
        $this->postJson('/api/datasets/synthetic', ['symbol' => 'R_75', 'timeframe' => 'M5', 'days' => 366])->assertUnprocessable()->assertJsonValidationErrors('days');
        $this->postJson('/api/datasets/synthetic', ['symbol' => 'R_75', 'timeframe' => 'M1', 'days' => 60])->assertCreated();
        $this->postJson('/api/datasets/synthetic', ['symbol' => 'R_75', 'timeframe' => 'M1', 'days' => 90])->assertUnprocessable()->assertJsonValidationErrors('days');
    }

    public function test_broker_downloads_have_a_capped_period_and_their_own_rate_limit(): void
    {
        $dataset = $this->dataset();
        $this->fakeEngine(['/internal/datasets/download' => ['id' => $dataset->id, 'bars' => 1000]]);
        $account = $this->account([], ConnectorType::Deriv);
        $this->actingAs($this->me());
        $body = fn (string $timeframe, string $start, string $end) => ['account_id' => $account->id, 'symbol' => 'R_75', 'timeframe' => $timeframe,
            'start' => $start, 'end' => $end];
        $this->postJson('/api/datasets/download', $body('M1', '2026-08-01', '2026-09-29'))->assertCreated(); // 59 days
        $this->postJson('/api/datasets/download', $body('M1', '2026-06-01', '2026-09-29'))->assertUnprocessable()->assertJsonValidationErrors('start');
        $this->postJson('/api/datasets/download', $body('M5', '2025-01-01', '2026-09-01'))->assertUnprocessable()->assertJsonValidationErrors('start');
        $this->postJson('/api/datasets/download', $body('H1', '2010-01-01', '2026-09-01'))->assertUnprocessable()->assertJsonValidationErrors('start');
        $this->postJson('/api/datasets/download', $body('H1', '2026-01-01', now()->addDays(30)->toDateString()))->assertUnprocessable()->assertJsonValidationErrors('end');
        Http::assertSentCount(1);
        foreach (range(1, 7) as $_) { // 12 broker calls a minute per user, counting the five above
            $this->postJson('/api/datasets/download', $body('H1', '2026-01-01', '2026-02-01'))->assertCreated();
        }
        $this->postJson('/api/datasets/download', $body('H1', '2026-01-01', '2026-02-01'))->assertStatus(429);
    }
}
