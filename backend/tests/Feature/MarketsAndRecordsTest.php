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

    public function test_an_unsynced_list_says_why_it_is_empty(): void
    {
        $this->engineDown();
        $account = $this->account();
        $this->actingAs($this->me())->getJson("/api/markets/instruments?account_id={$account->id}")->assertOk()
            ->assertJsonCount(0, 'instruments')->assertJsonPath('synced_at', null)
            ->assertJson(fn ($json) => $json->whereType('sync_error', 'string')->etc());
    }

    public function test_a_stale_or_refreshed_list_is_fetched_again_and_kept_when_the_broker_fails(): void
    {
        $account = $this->account();
        $this->symbol($account->connection_id, 'R_10', 'synthetic');
        Http::fake(['engine.test/internal/accounts/*/symbols*' => Http::response([])]);
        $this->actingAs($this->me())->getJson("/api/markets/instruments?account_id={$account->id}")->assertOk()->assertJsonPath('sync_error', null);
        Http::assertNothingSent(); // fresh: served from the stored list

        $this->getJson("/api/markets/instruments?account_id={$account->id}&refresh=1")->assertOk();
        Http::assertSentCount(1);

        BrokerSymbol::query()->update(['updated_at' => now()->subDay()]);
        $this->engineDown();
        $this->getJson("/api/markets/instruments?account_id={$account->id}")->assertOk()
            ->assertJsonPath('instruments.0.name', 'R_10')
            ->assertJson(fn ($json) => $json->whereType('sync_error', 'string')->etc());
    }

    private function symbol(string $connectionId, string $name, string $category): void
    {
        BrokerSymbol::query()->create(['connection_id' => $connectionId, 'name' => $name, 'canonical' => $name, 'category' => $category,
            'description' => $name, 'base_currency' => $name, 'quote_currency' => 'USD', 'digits' => 3, 'point' => '0.001', 'contract_size' => '1',
            'volume_min' => '1', 'volume_max' => '1', 'volume_step' => '1', 'trade_allowed' => true, 'market_open' => true]);
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

    public function test_candles_for_a_live_chart_come_from_the_engine_for_the_owner_only(): void
    {
        $account = $this->account();
        $candle = ['time' => '2026-10-14T03:40:00+00:00', 'open' => '6500.1', 'high' => '6501', 'low' => '6499.5', 'close' => '6500.8', 'volume' => 0];
        Http::fake(['engine.test/internal/accounts/*/candles*' => Http::response(['candles' => [$candle], 'simulated' => true])]);

        $this->actingAs($this->me())->getJson("/api/markets/candles?account_id={$account->id}&symbol=R_10&timeframe=M1&count=120")
            ->assertOk()->assertJsonPath('timeframe', 'M1')->assertJsonPath('candles.0.close', '6500.8');
        Http::assertSent(fn (Request $r) => str_contains($r->url(), '/candles') && $r['symbol'] === 'R_10' && (int) $r['count'] === 120 && $r['timeframe'] === 'M1');
        $this->getJson("/api/markets/candles?account_id={$account->id}&symbol=R_10&count=5000")->assertUnprocessable();

        $this->actingAs($this->user())->getJson("/api/markets/candles?account_id={$account->id}&symbol=R_10")->assertForbidden();
    }
}
