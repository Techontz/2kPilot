<?php

namespace Tests\Feature;

use App\Enums\ConnectorType;
use App\Models\AppNotification;
use App\Models\Backtest;
use App\Models\Dataset;
use App\Models\Order;
use App\Models\Signal;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\TradeEvent;
use App\Models\User;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Str;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

/**
 * Every user-owned record is invisible and untouchable for other users.
 * Alice owns everything below; Bob tries to read and change it.
 */
class TenantIsolationTest extends TestCase
{
    use CreatesTradingData;

    private User $alice;

    private User $bob;

    /** @var array<string, mixed> */
    private array $a;

    protected function setUp(): void
    {
        parent::setUp();
        Http::fake(); // nothing below may reach the engine
        $this->alice = $this->me();
        $this->bob = $this->user();
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id, 'label' => 'Alice paper']);
        $version = $this->strategyVersion();
        $signal = Signal::query()->create(['source' => 'MANUAL', 'account_id' => $account->id, 'symbol' => 'EURUSD', 'side' => 'BUY', 'timeframe' => 'M1',
            'bar_time' => now(), 'entry_type' => 'MARKET', 'entry_price' => '1.1', 'stop_loss' => '1.098', 'reasons' => [], 'status' => 'EXECUTED', 'risk_checks' => []]);
        $this->a = [
            'account' => $account,
            'open' => $this->openTrade($account),
            'closed' => $this->closedTrade($account, 10, '-1 hour', ['signal_id' => $signal->id]),
            'profile' => $this->defaultProfile(),
            'assignment' => StrategyAssignment::query()->create(['strategy_id' => $version->strategy_id, 'strategy_version_id' => $version->id,
                'account_id' => $account->id, 'symbol' => 'EURUSD']),
            'backtest' => Backtest::query()->create([
                'id' => (string) Str::uuid(), 'user_id' => $this->alice->id, 'kind' => 'SINGLE', 'status' => 'COMPLETED', 'strategy_key' => 'trend_pullback',
                'code_version' => '1.0.0', 'parameters' => [], 'symbol' => 'EURUSD', 'timeframe' => 'H1', 'data_source' => 'synthetic',
                'start' => now()->subMonth(), 'end' => now(), 'initial_capital' => '10000', 'account_currency' => 'USD', 'risk_settings' => [], 'costs' => [], 'config' => [],
            ]),
            'dataset' => Dataset::query()->create(['user_id' => $this->alice->id, 'symbol' => 'EURUSD', 'timeframe' => 'H1', 'source' => 'synthetic', 'source_ref' => 'seed-1']),
            'notification' => AppNotification::query()->create(['user_id' => $this->alice->id, 'type' => 'position.opened', 'severity' => 'info', 'title' => 't', 'message' => 'alice', 'data' => []]),
            'version' => $version,
        ];
        Order::query()->create(['client_order_id' => str_repeat('b', 24), 'account_id' => $account->id, 'signal_id' => $signal->id,
            'purpose' => 'ENTRY', 'symbol' => 'EURUSD', 'side' => 'BUY', 'order_type' => 'MARKET', 'volume' => '0.1', 'status' => 'FILLED', 'is_simulated' => true]);
        TradeEvent::query()->create(['account_id' => $account->id, 'signal_id' => $signal->id, 'event_type' => 'SIGNAL_GENERATED', 'message' => 'x', 'data' => []]);
        $this->snapshot($account, 10000);
    }

    public function test_indexes_never_list_another_users_records(): void
    {
        $this->actingAs($this->bob);
        $this->getJson('/api/brokers')->assertOk()->assertJsonCount(0);
        $this->getJson('/api/accounts')->assertOk()->assertJsonCount(0);
        $this->getJson('/api/positions')->assertOk()->assertJsonCount(0);
        $this->getJson('/api/orders')->assertOk()->assertJsonCount(0, 'data');
        $this->getJson('/api/history')->assertOk()->assertJsonCount(0, 'data');
        $this->getJson('/api/journal')->assertOk()->assertJsonCount(0, 'data');
        $this->getJson('/api/signals')->assertOk()->assertJsonCount(0, 'data');
        $this->getJson('/api/backtests')->assertOk()->assertJsonCount(0);
        $this->getJson('/api/datasets')->assertOk()->assertJsonCount(0);
        $this->getJson('/api/notifications')->assertOk()->assertJsonCount(0, 'data');
        $this->getJson('/api/notifications/unread-count')->assertJsonPath('count', 0);
        $this->getJson('/api/overview')->assertOk()->assertJsonPath('account', null);
        $this->getJson('/api/analytics/performance?environment=PAPER')->assertOk()->assertJsonPath('has_data', false);
        $risk = $this->getJson('/api/risk/profiles')->assertOk()->assertJsonCount(1)->json();
        $this->assertNotSame($this->a['profile']->id, $risk[0]['id']);
        // The built-in strategy is shared; Alice's assignment and results on it are not.
        $pullback = collect($this->getJson('/api/strategies')->assertOk()->json())->firstWhere('key', 'trend_pullback');
        $this->assertCount(0, $pullback['assignments']);
        $this->assertSame(0, $pullback['live_trades']);

        $this->actingAs($this->alice);
        $this->getJson('/api/accounts')->assertJsonCount(1);
        $this->getJson('/api/history')->assertJsonCount(1, 'data');
        $this->assertCount(1, collect($this->getJson('/api/strategies')->json())->firstWhere('key', 'trend_pullback')['assignments']);
    }

    public function test_another_users_records_cannot_be_read_by_id(): void
    {
        $a = $this->a;
        $this->actingAs($this->bob);
        $this->getJson("/api/accounts/{$a['account']->id}")->assertForbidden();
        $this->getJson("/api/trades/{$a['closed']->id}")->assertForbidden();
        $this->getJson("/api/backtests/{$a['backtest']->id}")->assertForbidden();
        $this->getJson("/api/backtests/{$a['backtest']->id}/trades")->assertForbidden();
        $this->getJson("/api/assignments/{$a['assignment']->id}/evaluations")->assertForbidden();
        $this->getJson("/api/risk/usage/{$a['account']->id}")->assertForbidden();
        $this->getJson("/api/overview?account_id={$a['account']->id}")->assertNotFound();
        $this->getJson("/api/markets/instruments?account_id={$a['account']->id}")->assertForbidden();
        $this->getJson("/api/markets/quotes?account_id={$a['account']->id}&symbols=EURUSD")->assertForbidden();
        $this->getJson("/api/analytics/performance?account_id={$a['account']->id}")->assertJsonPath('has_data', false);
        Http::assertNothingSent();
    }

    public function test_another_users_records_cannot_be_changed(): void
    {
        $a = $this->a;
        $this->actingAs($this->bob);
        $connection = $a['account']->connection_id;
        $this->patchJson("/api/accounts/{$a['account']->id}", ['trading_enabled' => false])->assertForbidden();
        $this->postJson("/api/accounts/{$a['account']->id}/sync")->assertForbidden();
        $this->postJson("/api/brokers/{$connection}/disconnect")->assertForbidden();
        $this->postJson("/api/brokers/{$connection}/reconnect")->assertForbidden();
        $this->deleteJson("/api/brokers/{$connection}")->assertForbidden();
        $this->putJson("/api/risk/profiles/{$a['profile']->id}", ['name' => 'mine now', 'risk_per_trade_pct' => 5, 'allowed_sessions' => [], 'max_data_age_seconds' => 60])->assertForbidden();
        $this->deleteJson("/api/risk/profiles/{$a['profile']->id}")->assertForbidden();
        $this->deleteJson("/api/backtests/{$a['backtest']->id}")->assertForbidden();
        $this->deleteJson("/api/datasets/{$a['dataset']->id}")->assertForbidden();
        $this->postJson("/api/assignments/{$a['assignment']->id}/enable")->assertForbidden();
        $this->postJson("/api/assignments/{$a['assignment']->id}/pause")->assertForbidden();
        $this->deleteJson("/api/assignments/{$a['assignment']->id}")->assertForbidden();
        $this->postJson('/api/assignments', ['strategy_version_id' => $a['version']->id, 'account_id' => $a['account']->id, 'symbol' => 'GBPUSD'])->assertNotFound();
        $this->postJson('/api/notifications/read', ['ids' => [$a['notification']->id]])->assertJsonPath('updated', 0);
        $this->postJson('/api/notifications/read')->assertJsonPath('updated', 0);
        // Bob's own risk profile cannot be put on Alice's account, nor Alice's on Bob's.
        $bobs = $this->account(['label' => 'Bob paper'], owner: $this->bob);
        $this->patchJson("/api/accounts/{$bobs->id}", ['risk_profile_id' => $a['profile']->id])->assertNotFound();

        $this->assertNull($a['notification']->fresh()->read_at);
        $this->assertDatabaseHas('broker_connections', ['id' => $connection, 'is_enabled' => true]);
        $this->assertDatabaseHas('risk_profiles', ['id' => $a['profile']->id, 'name' => 'Beginner']);
        $this->assertDatabaseHas('strategy_assignments', ['id' => $a['assignment']->id, 'status' => 'PAUSED']);
        Http::assertNothingSent();
    }

    public function test_another_users_account_cannot_be_traded(): void
    {
        $a = $this->a;
        $ticket = ['account_id' => $a['account']->id, 'symbol' => 'EURUSD', 'side' => 'BUY', 'volume' => '0.10', 'stop_loss' => '1.09',
            'idempotency_key' => 'ticket-0123456789abcdef', 'confirm' => true];
        $this->actingAs($this->bob);
        $this->postJson('/api/trade/preview', $ticket)->assertNotFound();
        $this->postJson('/api/trade/orders', $ticket)->assertNotFound();
        $this->postJson("/api/positions/{$a['open']->id}/close", ['confirm' => true])->assertForbidden();
        $this->putJson("/api/positions/{$a['open']->id}", ['stop_loss' => '1.09'])->assertForbidden();
        $this->postJson('/api/datasets/download', ['account_id' => $a['account']->id, 'symbol' => 'EURUSD', 'timeframe' => 'H1', 'start' => '2026-01-01', 'end' => '2026-02-01'])->assertNotFound();
        Http::assertNothingSent();
    }

    public function test_admins_can_read_but_never_trade_another_users_account(): void
    {
        $a = $this->a;
        $this->actingAs($this->admin());
        $this->getJson("/api/accounts/{$a['account']->id}")->assertOk();
        $this->getJson("/api/trades/{$a['closed']->id}")->assertOk();
        $this->getJson("/api/backtests/{$a['backtest']->id}")->assertOk();
        $this->postJson("/api/positions/{$a['open']->id}/close", ['confirm' => true])->assertForbidden();
        $this->patchJson("/api/accounts/{$a['account']->id}", ['trading_enabled' => false])->assertForbidden();
        $this->postJson("/api/assignments/{$a['assignment']->id}/enable")->assertForbidden();
        $this->postJson('/api/trade/orders', ['account_id' => $a['account']->id, 'symbol' => 'EURUSD', 'side' => 'BUY', 'volume' => '0.10',
            'stop_loss' => '1.09', 'idempotency_key' => 'ticket-0123456789abcdef', 'confirm' => true])->assertNotFound();
        Http::assertNothingSent();
    }

    public function test_admin_read_access_never_extends_to_actions(): void
    {
        $private = Strategy::query()->create(['user_id' => $this->alice->id, 'key' => 'rules', 'name' => 'Alice private', 'description' => 'mine']);
        $admin = $this->admin();
        $adminAccount = $this->account(['risk_profile_id' => $this->defaultProfile($admin)->id], ConnectorType::Paper, $admin);
        $this->actingAs($admin);
        $this->getJson("/api/accounts/{$this->a['account']->id}")->assertOk(); // reading is fine
        // Running or copying another user's private strategy.
        $this->postJson("/api/strategies/{$private->id}/activate", ['account_id' => $adminAccount->id, 'symbol' => 'EURUSD'])->assertForbidden();
        $this->postJson("/api/strategies/{$private->id}/copy", ['name' => 'Taken'])->assertForbidden();
        // Asking a broker through another user's connection.
        $account = $this->a['account']->id;
        $this->getJson("/api/markets/quotes?account_id={$account}&symbols=EURUSD")->assertForbidden();
        $this->getJson("/api/markets/instruments/EURUSD?account_id={$account}")->assertForbidden();
        $this->getJson("/api/markets/instruments?account_id={$account}")->assertForbidden();
        Http::assertNothingSent();
        $this->assertDatabaseMissing('strategies', ['name' => 'Taken']);
    }

    public function test_built_in_strategies_are_shared_but_read_only_for_users(): void
    {
        $this->fakeEngine(['/internal/strategies' => []]);
        $builtIn = $this->a['version']->strategy;
        $this->actingAs($this->bob);
        $this->getJson('/api/strategies')->assertOk()->assertJsonPath('0.built_in', true);
        $this->postJson("/api/strategies/{$builtIn->id}/versions", ['parameters' => ['ema_fast' => 20]])->assertForbidden();
        $copy = $this->postJson("/api/strategies/{$builtIn->id}/copy", ['name' => 'My pullback'])->assertCreated()
            ->assertJsonPath('user_id', $this->bob->id)->assertJsonPath('versions.0.version', 1)->json();
        $this->assertSame(50, $copy['versions'][0]['parameters']['ema_fast']);
        $this->postJson("/api/strategies/{$builtIn->id}/copy", ['name' => 'My pullback'])->assertJsonValidationErrors('name');
        // Bob's copy is his alone.
        $aliceSees = collect($this->actingAs($this->alice)->getJson('/api/strategies')->json());
        $this->assertNotContains($copy['id'], $aliceSees->pluck('id'));
        $this->assertTrue($aliceSees->every(fn ($s) => $s['built_in']));
        $this->postJson("/api/strategies/{$copy['id']}/copy", ['name' => 'Stolen'])->assertForbidden();
    }

    public function test_shared_datasets_are_readable_by_everyone_and_deletable_only_by_admins(): void
    {
        $shared = Dataset::query()->create(['user_id' => null, 'symbol' => 'GBPUSD', 'timeframe' => 'H1', 'source' => 'synthetic', 'source_ref' => 'seed-2']);
        $this->actingAs($this->bob)->getJson('/api/datasets')->assertOk()->assertJsonCount(1)->assertJsonPath('0.id', $shared->id);
        $this->deleteJson("/api/datasets/{$shared->id}")->assertForbidden();
        $this->actingAs($this->admin())->deleteJson("/api/datasets/{$shared->id}")->assertOk();
    }
}
