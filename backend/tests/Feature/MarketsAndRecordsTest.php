<?php

namespace Tests\Feature;

use App\Models\AppNotification;
use App\Models\BrokerSymbol;
use App\Models\Order;
use App\Models\Signal;
use App\Models\TradeEvent;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class MarketsAndRecordsTest extends TestCase
{
    use CreatesTradingData;

    public function test_instruments_come_from_the_connected_broker(): void
    {
        Http::fake();
        $account = $this->account();
        foreach ([['EURUSD', 'forex'], ['R_100', 'synthetic']] as [$name, $category]) {
            BrokerSymbol::query()->create(['connection_id' => $account->connection_id, 'name' => $name, 'canonical' => $name, 'category' => $category,
                'base_currency' => 'EUR', 'quote_currency' => 'USD', 'digits' => 5, 'point' => '0.00001', 'contract_size' => '100000',
                'volume_min' => '0.01', 'volume_max' => '50', 'volume_step' => '0.01', 'trade_allowed' => true, 'market_open' => true]);
        }
        $this->actingAs($this->me())->getJson("/api/markets/instruments?account_id={$account->id}")->assertOk()
            ->assertJsonPath('provider', 'Paper Trading')->assertJsonPath('simulated', true)
            ->assertJsonPath('categories.forex', 1)->assertJsonCount(2, 'instruments');
        $this->getJson("/api/markets/instruments?account_id={$account->id}&category=synthetic")->assertJsonCount(1, 'instruments');
        Http::assertNothingSent();
    }

    public function test_quotes_are_proxied_from_the_engine(): void
    {
        $this->fakeEngine(['/internal/accounts/' => ['quotes' => ['EURUSD' => ['bid' => '1.1', 'ask' => '1.10012', 'spread' => '0.00012']], 'errors' => [], 'simulated' => true]]);
        $account = $this->account();
        $this->actingAs($this->me())->getJson("/api/markets/quotes?account_id={$account->id}&symbols=EURUSD")
            ->assertOk()->assertJsonPath('quotes.EURUSD.ask', '1.10012');
        Http::assertSent(fn (Request $r) => str_contains($r->url(), 'symbols=EURUSD'));
    }

    public function test_trade_detail_shows_the_whole_decision_chain(): void
    {
        $account = $this->account();
        $signal = Signal::query()->create(['source' => 'MANUAL', 'account_id' => $account->id, 'symbol' => 'EURUSD', 'side' => 'BUY', 'timeframe' => 'M1',
            'bar_time' => now(), 'entry_type' => 'MARKET', 'entry_price' => '1.1', 'stop_loss' => '1.098', 'reasons' => ['Manual ticket'], 'status' => 'EXECUTED', 'risk_checks' => [['rule' => 'Kill switch', 'passed' => true, 'detail' => 'released']]]);
        $trade = $this->closedTrade($account, 15, '-1 hour', ['signal_id' => $signal->id]);
        Order::query()->create(['client_order_id' => str_repeat('a', 24), 'account_id' => $account->id, 'signal_id' => $signal->id, 'trade_id' => $trade->id,
            'purpose' => 'ENTRY', 'symbol' => 'EURUSD', 'side' => 'BUY', 'order_type' => 'MARKET', 'volume' => '0.1', 'status' => 'FILLED', 'is_simulated' => true]);
        foreach (['SIGNAL_GENERATED', 'RISK_APPROVED', 'ORDER_SUBMITTED', 'ORDER_FILLED', 'POSITION_OPENED'] as $type) {
            TradeEvent::query()->create(['account_id' => $account->id, 'signal_id' => $signal->id, 'event_type' => $type, 'message' => $type, 'data' => []]);
        }
        $body = $this->actingAs($this->me())->getJson("/api/trades/{$trade->id}")->assertOk()->json();
        $this->assertSame('MANUAL', $body['trade']['source']);
        $this->assertSame('Kill switch', $body['signal']['risk_checks'][0]['rule']);
        $this->assertCount(1, $body['orders']);
        $this->assertSame('SIGNAL_GENERATED', $body['events'][0]['event_type']);
        $this->getJson('/api/history')->assertOk()->assertJsonPath('data.0.id', $trade->id);
        $this->getJson('/api/journal')->assertOk()->assertJsonCount(5, 'data');
        $this->getJson('/api/signals?source=MANUAL')->assertOk()->assertJsonPath('data.0.status', 'EXECUTED');
        $this->getJson('/api/orders')->assertOk()->assertJsonPath('data.0.status', 'FILLED');
    }

    public function test_notifications_can_be_listed_and_marked_read(): void
    {
        foreach (range(1, 3) as $i) {
            AppNotification::query()->create(['user_id' => $this->me()->id, 'type' => 'position.opened', 'severity' => 'info', 'title' => 't', 'message' => "m{$i}", 'data' => []]);
        }
        $this->actingAs($this->me())->getJson('/api/notifications/unread-count')->assertJsonPath('count', 3);
        $first = $this->getJson('/api/notifications')->json('data.0.id');
        $this->postJson('/api/notifications/read', ['ids' => [$first]])->assertJsonPath('updated', 1);
        $this->getJson('/api/notifications/unread-count')->assertJsonPath('count', 2);
        $this->postJson('/api/notifications/read')->assertJsonPath('updated', 2);
    }

    public function test_system_status_reports_configuration(): void
    {
        $this->engineDown();
        $this->actingAs($this->me())->getJson('/api/system/status')->assertOk()
            ->assertJsonPath('engine.status', 'unreachable')
            ->assertJsonPath('live_trading_enabled', false)
            ->assertJsonPath('broker_vault_configured', true)
            ->assertJsonPath('deriv_app_id_configured', false);
    }
}
