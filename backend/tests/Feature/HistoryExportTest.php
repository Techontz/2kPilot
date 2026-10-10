<?php

namespace Tests\Feature;

use App\Enums\ConnectorType;
use App\Http\Controllers\Api\RecordsController;
use App\Models\Strategy;
use App\Models\StrategyVersion;
use App\Models\Trade;
use App\Models\TradingAccount;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

/** Trade history with contract details, its filters and the CSV export. */
class HistoryExportTest extends TestCase
{
    use CreatesTradingData;

    private function contractTrade(TradingAccount $account, array $overrides = []): Trade
    {
        return $this->closedTrade($account, -1, '-1 hour', array_merge([
            'symbol' => 'R_100', 'side' => 'SELL', 'volume' => '1', 'entry_price' => '1234.5', 'exit_price' => '1235.1',
            'entry_time' => now()->subHour()->subMinutes(5), 'exit_time' => now()->subHour(),
            'contract_family' => 'RISE_FALL', 'contract_type' => 'PUT', 'broker_contract_id' => '250001', 'stake' => '1.000000', 'payout' => '1.950000',
            'duration' => 5, 'duration_unit' => 'm', 'expires_at' => now()->subHour(), 'entry_spot' => '1234.56', 'exit_spot' => '1235.12',
            'fees' => '0', 'outcome' => 'LOST', 'longcode' => 'Win payout if Volatility 100 Index is strictly lower than entry spot at 5 minutes after contract start time.',
            'exit_reason' => 'EXPIRED',
        ], $overrides));
    }

    private function csv(string $content): array
    {
        return array_map('str_getcsv', array_values(array_filter(explode("\n", $content))));
    }

    public function test_history_items_carry_the_contract_details(): void
    {
        $this->travelTo(now()->setTime(12, 0));
        $trade = $this->contractTrade($this->account([], ConnectorType::Deriv));
        $item = $this->actingAs($this->me())->getJson('/api/history')->assertOk()->json('data.0');
        $this->assertSame($trade->id, $item['id']);
        foreach (['contract_family' => 'RISE_FALL', 'contract_type' => 'PUT', 'broker_contract_id' => '250001', 'duration' => 5, 'duration_unit' => 'm', 'outcome' => 'LOST'] as $key => $value) {
            $this->assertSame($value, $item[$key], $key);
        }
        $this->assertSame(300, $item['duration_seconds']);
        $this->assertStringStartsWith('Win payout if', $item['longcode']);
        $this->assertNotNull($item['expires_at']);
        $this->assertSame('1.000000', $item['stake']);

        $open = $this->openTrade($this->account(), ['entry_time' => now()->subMinutes(10)]);
        $position = $this->getJson('/api/positions')->assertOk()->json('0');
        $this->assertSame($open->id, $position['id']);
        $this->assertSame('SPOT', $position['contract_family']);
        $this->assertSame(600, $position['duration_seconds']); // still open: held until now
    }

    public function test_history_filters_by_dates_and_strategy(): void
    {
        $this->travelTo(now()->setTime(12, 0));
        $account = $this->account();
        $version = $this->strategyVersion();
        $other = StrategyVersion::query()->create(['strategy_id' => Strategy::query()->create(['key' => 'breakout', 'name' => 'Breakout', 'description' => 't'])->id,
            'version' => 1, 'code_version' => '1.0.0', 'parameters' => [], 'notes' => '']);
        $old = $this->closedTrade($account, 5, '-10 days', ['strategy_version_id' => $version->id]);
        $recent = $this->closedTrade($account, 7, '-1 hour', ['strategy_version_id' => $version->id]);
        $this->closedTrade($account, 9, '-2 hours', ['strategy_version_id' => $other->id]);
        $this->actingAs($this->me());
        $this->getJson('/api/history')->assertJsonCount(3, 'data');
        $this->getJson('/api/history?strategy_id='.$version->strategy_id)->assertJsonCount(2, 'data');
        $this->getJson('/api/history?strategy_id='.$version->strategy_id.'&from='.now()->subDays(2)->toDateString())
            ->assertJsonCount(1, 'data')->assertJsonPath('data.0.id', $recent->id);
        $this->getJson('/api/history?to='.now()->subDays(5)->toDateString())->assertJsonCount(1, 'data')->assertJsonPath('data.0.id', $old->id);
        $this->getJson('/api/history?from=yesterday-ish')->assertJsonValidationErrors('from');
    }

    public function test_export_streams_the_users_closed_trades_as_csv(): void
    {
        $this->travelTo(now()->setTime(12, 0));
        $deriv = $this->account(['label' => 'Deriv demo'], ConnectorType::Deriv);
        $paper = $this->account(['label' => '=HYPERLINK("x")']);
        $version = $this->strategyVersion();
        $this->contractTrade($deriv, ['strategy_version_id' => $version->id]);
        $this->closedTrade($paper, 12.5, '-3 hours', ['commission' => '0.7']);
        $this->openTrade($paper); // open trades are not history
        $this->closedTrade($this->account([], ConnectorType::Paper, $this->user()), 99); // someone else's

        $response = $this->actingAs($this->me())->get('/api/history/export?format=csv')->assertOk();
        $this->assertStringStartsWith('text/csv', $response->headers->get('Content-Type'));
        $this->assertStringContainsString('2kpilot-history-'.now()->format('Ymd').'.csv', $response->headers->get('Content-Disposition'));
        $rows = $this->csv($response->streamedContent());
        $this->assertSame(RecordsController::EXPORT_COLUMNS, $rows[0]);
        $this->assertSame(['opened_at', 'closed_at', 'account', 'environment', 'symbol', 'strategy', 'contract_type', 'direction', 'stake/volume',
            'entry', 'exit', 'fees', 'payout', 'net_pnl', 'outcome', 'duration_seconds'], $rows[0]);
        $this->assertCount(3, $rows); // header + my two closed trades
        $spot = array_combine($rows[0], $rows[1]); // oldest first
        $contract = array_combine($rows[0], $rows[2]);

        $this->assertSame("'=HYPERLINK(\"x\")", $spot['account']); // never a spreadsheet formula
        $this->assertSame(['PAPER', 'EURUSD', 'SPOT', 'BUY', '0.1000', '1.1000000000', '1.1010000000', '0.700000', '', '12.500000', '', '7200'],
            [$spot['environment'], $spot['symbol'], $spot['contract_type'], $spot['direction'], $spot['stake/volume'], $spot['entry'], $spot['exit'],
                $spot['fees'], $spot['payout'], $spot['net_pnl'], $spot['outcome'], $spot['duration_seconds']]);
        $this->assertSame(['Deriv demo', 'DEMO', 'R_100', 'Trend Pullback V1', 'PUT', 'SELL', '1.000000', '1234.5600000000', '1235.1200000000', '0.000000', '1.950000', 'LOST', '300'],
            [$contract['account'], $contract['environment'], $contract['symbol'], $contract['strategy'], $contract['contract_type'], $contract['direction'],
                $contract['stake/volume'], $contract['entry'], $contract['exit'], $contract['fees'], $contract['payout'], $contract['outcome'], $contract['duration_seconds']]);
        $this->assertSame(now()->subHour()->subMinutes(5)->toIso8601String(), $contract['opened_at']);
        $this->assertDatabaseHas('audit_logs', ['action' => 'history.exported', 'actor_user_id' => $this->me()->id]);
    }

    public function test_export_filters_and_validation(): void
    {
        $this->travelTo(now()->setTime(12, 0));
        $deriv = $this->account([], ConnectorType::Deriv);
        $paper = $this->account();
        $version = $this->strategyVersion();
        $this->contractTrade($deriv, ['strategy_version_id' => $version->id]);
        $this->closedTrade($paper, 3, '-3 days');
        $this->actingAs($this->me());
        $count = fn (string $query) => count($this->csv($this->get('/api/history/export?format=csv&'.$query)->assertOk()->streamedContent())) - 1;
        $this->assertSame(1, $count('account_id='.$deriv->id));
        $this->assertSame(1, $count('strategy_id='.$version->strategy_id));
        $this->assertSame(1, $count('from='.now()->subDay()->toDateString()));
        $this->assertSame(1, $count('to='.now()->subDays(2)->toDateString()));
        $this->assertSame(0, $count('account_id='.$this->account([], ConnectorType::Paper, $this->user())->id)); // not mine: nothing
        $this->getJson('/api/history/export')->assertJsonValidationErrors('format');
        $this->getJson('/api/history/export?format=xlsx')->assertJsonValidationErrors('format');
        $this->getJson('/api/history/export?format=csv&from=soon&account_id=123')->assertJsonValidationErrors(['from', 'account_id']);
    }

    public function test_history_and_export_filter_by_outcome(): void
    {
        $this->travelTo(now()->setTime(12, 0));
        $account = $this->account();
        $win = $this->closedTrade($account, 25);
        $loss = $this->closedTrade($account, -10, '-2 hours');
        $even = $this->closedTrade($account, 0, '-3 hours');
        $this->closedTrade($this->account([], ConnectorType::Paper, $this->user()), 99); // someone else's win
        $this->actingAs($this->me());
        foreach (['win' => $win, 'loss' => $loss, 'even' => $even] as $outcome => $trade) {
            $ids = array_column($this->getJson("/api/history?outcome={$outcome}")->assertOk()->json('data'), 'id');
            $this->assertSame([$trade->id], $ids, $outcome);
            $rows = $this->csv($this->get("/api/history/export?format=csv&outcome={$outcome}")->assertOk()->streamedContent());
            $this->assertCount(2, $rows, $outcome); // header + one trade
        }
        $this->assertCount(3, $this->getJson('/api/history')->json('data'));
        $this->getJson('/api/history?outcome=draw')->assertJsonValidationErrors('outcome');
        $this->getJson('/api/history/export?format=csv&outcome=big')->assertJsonValidationErrors('outcome');
    }
}
