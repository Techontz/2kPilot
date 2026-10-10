<?php

namespace Tests\Feature;

use App\Enums\ConnectionStatus;
use App\Enums\ConnectorType;
use App\Models\Backtest;
use App\Models\BrokerSymbol;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\TradingAccount;
use App\Services\Mfa\TwoFactorService;
use App\Services\Trading\TradingControl;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use PragmaRX\Google2FA\Google2FA;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

/** The Overview's setup checklist, blockers, active strategies and charts. */
class OverviewTest extends TestCase
{
    use CreatesTradingData;

    private function assignment(TradingAccount $account, string $status, array $contract = [], string $symbol = 'EURUSD'): StrategyAssignment
    {
        $version = $this->strategyVersion();

        return StrategyAssignment::query()->create(array_merge([
            'strategy_id' => $version->strategy_id, 'strategy_version_id' => $version->id, 'account_id' => $account->id,
            'symbol' => $symbol, 'status' => $status,
        ], $contract));
    }

    public function test_without_an_account_the_overview_is_an_empty_setup(): void
    {
        $body = $this->actingAs($this->me())->getJson('/api/overview')->assertOk()->json();
        $this->assertNull($body['account']);
        $this->assertSame('DEMO', $body['robot']['trading_mode']);
        foreach (['blockers', 'active_strategies', 'positions', 'daily_pnl', 'balance_history'] as $key) {
            $this->assertSame([], $body[$key], $key);
        }
        $this->assertSame([
            'has_broker' => false, 'has_account' => false, 'has_strategy' => false, 'has_backtest' => false,
            'has_active_strategy' => false, 'trading_started' => false, 'mfa_enabled' => false,
        ], $body['setup']);
    }

    public function test_account_and_broker_details(): void
    {
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id, 'balance' => '10050.25', 'equity' => '10034.5'], ConnectorType::Deriv);
        $account->connection->update(['last_connected_at' => now()->subMinute()]);
        $body = $this->actingAs($this->me())->getJson("/api/overview?account_id={$account->id}")->assertOk()->json();
        $this->assertSame($account->id, $body['account']['id']);
        $this->assertEquals(10050.25, $body['account']['balance']);
        $this->assertEquals(10034.5, $body['account']['equity']);
        $this->assertSame($account->broker_account_id, $body['account']['broker_account_id']);
        $this->assertSame($this->defaultProfile()->id, $body['account']['risk_profile_id']);
        $this->assertSame($account->connection_id, $body['account']['connection_id']);
        $this->assertNotNull($body['account']['last_connected_at']);
        $this->assertSame('deriv', $body['broker']['connector_type']);
        $this->assertSame('CONNECTED', $body['broker']['connection_status']);
        $this->assertSame($body['account']['broker'], $body['broker']['name']);
        $this->assertArrayHasKey('connection_detail', $body['broker']);
        $this->assertSame('ENABLE LIVE TRADING', $body['robot']['live_confirmation_phrase']);
    }

    public function test_blockers_explain_why_nothing_trades(): void
    {
        $this->travelTo('2026-03-04 14:00:00'); // a Wednesday: the EURUSD market is open
        $account = $this->account();
        $codes = fn () => array_column($this->getJson("/api/overview?account_id={$account->id}")->json('blockers'), 'code');
        $this->actingAs($this->me());
        $this->assertEqualsCanonicalizing(['trading_stopped', 'account_trading_disabled', 'engine_offline', 'risk_profile_missing', 'no_active_strategy'], $codes());
        $blocker = collect($this->getJson('/api/overview')->json('blockers'))->firstWhere('code', 'trading_stopped');
        $this->assertSame('Trading is stopped — press Start when you are ready.', $blocker['message']);

        $account->update(['trading_enabled' => true, 'risk_profile_id' => $this->defaultProfile()->id]);
        $this->assignment($account, 'ENABLED');
        $this->engineAlive();
        app(TradingControl::class)->resume($this->me());
        $this->assertSame([], $codes());

        $account->connection->update(['status' => ConnectionStatus::Disconnected]);
        $blockers = $this->getJson("/api/overview?account_id={$account->id}")->json('blockers');
        $this->assertSame([['code' => 'broker_disconnected', 'message' => 'The broker connection is disconnected.']], $blockers);
    }

    public function test_active_strategies_are_the_enabled_assignments_in_plain_words(): void
    {
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id], ConnectorType::Deriv);
        $rise = $this->assignment($account, 'ENABLED', ['contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm'], 'R_100');
        $this->assignment($account, 'ENABLED', ['contract_family' => 'MULTIPLIER', 'multiplier' => 100, 'stake' => '2'], 'R_50');
        $this->assignment($account, 'PAUSED', ['contract_family' => 'RISE_FALL', 'duration' => 1, 'duration_unit' => 't'], 'R_25');
        $this->assignment($this->account([], ConnectorType::Deriv, $this->user()), 'ENABLED', [], 'R_10'); // someone else's
        $body = $this->actingAs($this->me())->getJson("/api/overview?account_id={$account->id}")->assertOk()->json();
        $active = collect($body['active_strategies'])->keyBy('symbol');
        $this->assertEqualsCanonicalizing(['R_100', 'R_50'], $active->keys()->all());
        $this->assertSame($rise->id, $active['R_100']['assignment_id']);
        $this->assertSame('Trend Pullback V1', $active['R_100']['strategy']);
        $this->assertSame(1, $active['R_100']['version']);
        $this->assertSame('RISE_FALL', $active['R_100']['contract']['contract_family']);
        $this->assertSame('Rise/Fall · 5 minutes · stake from risk profile (1.00)', $active['R_100']['contract_summary']);
        $this->assertSame('Multiplier ×100 · stake 2.00', $active['R_50']['contract_summary']);
        $this->assertSame(2, $body['figures']['active_strategies']);
        $this->assertNotContains('no_active_strategy', array_column($body['blockers'], 'code'));
    }

    public function test_daily_pnl_balance_history_and_positions(): void
    {
        $this->travelTo(now()->setTime(12, 0));
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id], ConnectorType::Deriv);
        $this->closedTrade($account, 30, '-1 hour');
        $this->closedTrade($account, -10, '-2 hours');
        $this->closedTrade($account, 7, '-5 days');
        $this->closedTrade($account, 1000, '-40 days'); // outside the 30 days
        $theirs = $this->account([], ConnectorType::Deriv, $this->user());
        $this->closedTrade($theirs, 500, '-1 hour'); // someone else's: never counted
        $this->snapshot($account, 10000, '-10 days');
        $this->snapshot($account, 10010, '-10 days +1 hour');
        $this->snapshot($account, 10020, '-1 day');
        $this->snapshot($account, 9000, '-45 days');
        $open = $this->openTrade($account, ['symbol' => 'R_100', 'contract_family' => 'RISE_FALL', 'contract_type' => 'CALL', 'stake' => '1',
            'duration' => 5, 'duration_unit' => 'm', 'expires_at' => now()->addMinutes(3)]);
        $this->openTrade($account, ['symbol' => 'R_50']);

        $body = $this->actingAs($this->me())->getJson("/api/overview?account_id={$account->id}")->assertOk()->json();
        $days = $body['daily_pnl'];
        $this->assertCount(30, $days);
        $this->assertSame(now()->toDateString(), $days[29]['date']);
        $this->assertSame(now()->subDays(29)->toDateString(), $days[0]['date']);
        $this->assertEquals(20, $days[29]['net_pnl']);
        $this->assertSame(2, $days[29]['trades']);
        $this->assertEquals(7, $days[24]['net_pnl']);
        $this->assertEquals(27, array_sum(array_column($days, 'net_pnl')));
        $this->assertSame(3, array_sum(array_column($days, 'trades')));
        $this->assertEquals(1027, $body['figures']['total_pnl']); // all-time, still only mine

        $this->assertEquals([10010, 10020], array_column($body['balance_history'], 'balance')); // last per day, 30 days
        $this->assertSame(['t', 'balance', 'equity'], array_keys($body['balance_history'][0]));

        $this->assertCount(2, $body['positions']);
        $position = collect($body['positions'])->firstWhere('id', $open->id);
        $this->assertSame('RISE_FALL', $position['contract_family']);
        $this->assertSame('CALL', $position['contract_type']);
        $this->assertNotNull($position['expires_at']);
        $this->assertSame('USD', $position['account']['currency']);
        $this->assertCount(4, $body['recent_trades']); // mine only
        $this->assertArrayHasKey('outcome', $body['recent_trades'][0]);
    }

    public function test_setup_flags_follow_what_the_user_has_done(): void
    {
        $setup = fn () => $this->getJson('/api/overview')->json('setup');
        $this->actingAs($me = $this->me());
        $account = $this->account();
        $this->assertSame(['has_broker' => true, 'has_account' => true, 'has_strategy' => false, 'has_backtest' => false,
            'has_active_strategy' => false, 'trading_started' => false, 'mfa_enabled' => false], $setup());

        $assignment = $this->assignment($account, 'PAUSED');
        $this->assertTrue($setup()['has_strategy']);
        $this->assertFalse($setup()['has_active_strategy']);
        $assignment->update(['status' => 'ENABLED']);
        $this->assertTrue($setup()['has_active_strategy']);

        Backtest::query()->create([
            'id' => (string) Str::uuid(), 'user_id' => $me->id, 'kind' => 'SINGLE', 'status' => 'RUNNING', 'strategy_key' => 'trend_pullback', 'code_version' => '1.0.0',
            'parameters' => [], 'symbol' => 'EURUSD', 'timeframe' => 'H1', 'data_source' => 'synthetic',
            'start' => now()->subMonths(3), 'end' => now(), 'initial_capital' => '10000', 'account_currency' => 'USD',
            'risk_settings' => [], 'costs' => [], 'config' => [],
        ]);
        $this->assertFalse($setup()['has_backtest']); // not finished yet
        Backtest::query()->update(['status' => 'COMPLETED']);
        $this->assertTrue($setup()['has_backtest']);

        app(TradingControl::class)->resume($me);
        $this->assertTrue($setup()['trading_started']);
        $mfa = app(TwoFactorService::class);
        $secret = $mfa->begin($me)['secret'];
        $this->assertNotNull($mfa->confirm($me->fresh(), (new Google2FA)->getCurrentOtp($secret)));
        $this->actingAs($me->fresh());
        $this->assertTrue($setup()['mfa_enabled']);
    }

    /** Everything set up and running, so only the market can block. */
    private function readyAccount(ConnectorType $type = ConnectorType::Paper): TradingAccount
    {
        $account = $this->account(['trading_enabled' => true, 'risk_profile_id' => $this->defaultProfile()->id], $type);
        $this->engineAlive();
        app(TradingControl::class)->resume($this->me());

        return $account;
    }

    private function blockersOf(TradingAccount $account): array
    {
        return $this->actingAs($this->me())->getJson("/api/overview?account_id={$account->id}")->assertOk()->json('blockers');
    }

    private function symbol(TradingAccount $account, string $name, string $category, ?bool $open): void
    {
        BrokerSymbol::query()->create([
            'connection_id' => $account->connection_id, 'name' => $name, 'canonical' => $name, 'category' => $category,
            'base_currency' => 'USD', 'quote_currency' => 'USD', 'digits' => 2, 'point' => '0.01', 'contract_size' => 1,
            'volume_min' => 1, 'volume_max' => 100, 'volume_step' => 1, 'trade_allowed' => true, 'market_open' => $open,
        ]);
    }

    public function test_a_closed_forex_market_blocks_until_it_reopens_but_synthetic_indices_never_close(): void
    {
        $this->travelTo('2026-10-10 12:00:00'); // Saturday
        $account = $this->readyAccount();
        $this->assignment($account, 'ENABLED', symbol: 'EURUSD');
        $this->assignment($account, 'ENABLED', symbol: 'R_75');
        $this->assertSame([['code' => 'market_closed', 'message' => 'EURUSD market is closed until Sunday 21:00 UTC.']], $this->blockersOf($account));

        $this->travelTo('2026-10-11 20:59:00'); // Sunday, a minute before the open
        $this->engineAlive();
        $this->assertSame('market_closed', $this->blockersOf($account)[0]['code']);
        $this->travelTo('2026-10-11 21:00:00');
        $this->engineAlive();
        $this->assertSame([], $this->blockersOf($account));
        $this->travelTo('2026-10-16 21:00:00'); // Friday close
        $this->engineAlive();
        $this->assertSame(['EURUSD market is closed until Sunday 21:00 UTC.'], array_column($this->blockersOf($account), 'message'));

        // Switching a strategy on says so as well.
        $template = Strategy::query()->where('slug', 'rsi-mean-reversion')->firstOrFail();
        $res = $this->postJson("/api/strategies/{$template->id}/activate", ['account_id' => $account->id, 'symbol' => 'GBPUSD'])->assertOk()
            ->assertJsonPath('will_trade', false)->json();
        $this->assertSame([['code' => 'market_closed', 'message' => 'GBPUSD market is closed until Sunday 21:00 UTC.']], $res['blockers']);
        StrategyAssignment::query()->where('symbol', 'GBPUSD')->update(['status' => 'PAUSED']);

        // A paused strategy's market does not matter.
        StrategyAssignment::query()->where('account_id', $account->id)->where('symbol', 'EURUSD')->update(['status' => 'PAUSED']);
        $this->assertSame([], $this->blockersOf($account));
    }

    public function test_paper_accounts_use_the_simulated_clock(): void
    {
        $this->travelTo('2026-10-10 12:00:00'); // real time: Saturday
        $account = $this->readyAccount();
        $this->assignment($account, 'ENABLED', symbol: 'EURUSD');
        $state = fn (string $cursor) => DB::table('paper_states')->updateOrInsert(
            ['connection_id' => $account->connection_id], ['state' => json_encode(['market' => ['cursor' => $cursor]])]);

        $state('2026-09-16T10:05:00+00:00'); // the simulation is still on a Wednesday
        $this->assertSame([], $this->blockersOf($account));

        $state('2026-09-19T03:00:00+00:00'); // …and later reaches its own weekend
        $this->assertSame([[
            'code' => 'market_closed',
            'message' => 'EURUSD market is closed in the Paper simulation until Sunday 21:00 UTC (simulated time).',
        ]], $this->blockersOf($account));
    }

    public function test_broker_reported_closures_block_and_activation_reports_them(): void
    {
        $this->travelTo('2026-03-04 14:00:00'); // a Wednesday
        $account = $this->readyAccount(ConnectorType::Deriv);
        $this->assignment($account, 'ENABLED', symbol: 'OTC_DJI');
        $this->symbol($account, 'OTC_DJI', 'indices', false);
        $this->assertSame([['code' => 'market_closed', 'message' => 'OTC_DJI market is closed right now (as reported by the broker).']], $this->blockersOf($account));
        BrokerSymbol::query()->where('name', 'OTC_DJI')->update(['market_open' => true]);
        $this->assertSame([], $this->blockersOf($account));

        // Deriv forex names follow the forex week too.
        $this->travelTo('2026-03-07 09:30:00'); // Saturday
        $this->engineAlive();
        $this->symbol($account, 'frxEURUSD', 'forex', true); // stale "open" from Friday
        $this->assignment($account, 'ENABLED', symbol: 'frxEURUSD');
        $this->assertSame(['frxEURUSD market is closed until Sunday 21:00 UTC.'], array_column($this->blockersOf($account), 'message'));
    }

    public function test_another_users_account_is_not_found(): void
    {
        $theirs = $this->account([], ConnectorType::Paper, $this->user());
        $this->actingAs($this->me())->getJson("/api/overview?account_id={$theirs->id}")->assertNotFound();
    }
}
