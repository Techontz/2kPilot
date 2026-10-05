<?php

namespace Tests\Support;

use App\Enums\AccountEnvironment;
use App\Enums\ConnectionStatus;
use App\Enums\ConnectorType;
use App\Models\AccountSnapshot;
use App\Models\BrokerConnection;
use App\Models\RiskProfile;
use App\Models\Strategy;
use App\Models\StrategyVersion;
use App\Models\Trade;
use App\Models\TradingAccount;
use Illuminate\Support\Str;

/** Rows as the trading engine / Broker Center would write them. */
trait CreatesTradingData
{
    protected function defaultProfile(): RiskProfile
    {
        return RiskProfile::query()->where('name', RiskProfile::DEFAULT_NAME)->firstOrFail();
    }

    protected function account(array $overrides = [], ConnectorType $type = ConnectorType::Paper): TradingAccount
    {
        $environment = $overrides['environment'] ?? ($type === ConnectorType::Paper ? AccountEnvironment::Paper : AccountEnvironment::Demo);
        $connection = BrokerConnection::query()->create([
            'label' => $overrides['label'] ?? 'Test account',
            'connector_type' => $type,
            'expected_environment' => $environment === AccountEnvironment::Unknown ? AccountEnvironment::Demo : $environment,
            'settings' => [],
            'credentials_encrypted' => $type === ConnectorType::Paper ? null : 'sealed',
            'status' => ConnectionStatus::Connected,
            'status_detail' => 'Connected',
        ]);

        return TradingAccount::query()->create(array_merge([
            'connection_id' => $connection->id,
            'broker_account_id' => 'ACC-'.Str::random(6),
            'label' => 'Test account',
            'currency' => 'USD',
            'environment' => $environment,
            'trading_enabled' => false,
            'risk_profile_id' => null,
            'capabilities' => [],
            'balance' => '10000',
            'equity' => '10000',
        ], array_diff_key($overrides, ['environment' => 1]), ['environment' => $environment]));
    }

    protected function strategyVersion(): StrategyVersion
    {
        $strategy = Strategy::query()->firstOrCreate(['key' => 'trend_pullback'], ['name' => 'Trend Pullback V1', 'description' => 'test']);

        return StrategyVersion::query()->firstOrCreate(
            ['strategy_id' => $strategy->id, 'version' => 1],
            ['code_version' => '1.0.0', 'parameters' => ['ema_fast' => 50, 'ema_slow' => 200], 'notes' => 'defaults'],
        );
    }

    protected function closedTrade(TradingAccount $account, float $pnl, string $exit = '-1 hour', array $overrides = []): Trade
    {
        return Trade::query()->create(array_merge([
            'account_id' => $account->id,
            'symbol' => 'EURUSD',
            'side' => 'BUY',
            'status' => 'CLOSED',
            'volume' => '0.10',
            'entry_price' => '1.10000',
            'entry_time' => now()->modify($exit)->subHours(2),
            'exit_price' => '1.10100',
            'exit_time' => now()->modify($exit),
            'exit_reason' => $pnl >= 0 ? 'TAKE_PROFIT' : 'STOP_LOSS',
            'net_pnl' => (string) $pnl,
            'gross_pnl' => (string) $pnl,
            'risk_amount' => '20',
            'r_multiple' => (string) round($pnl / 20, 2),
            'session' => 'LONDON',
            'is_simulated' => $account->isPaper(),
        ], $overrides));
    }

    protected function openTrade(TradingAccount $account, array $overrides = []): Trade
    {
        return Trade::query()->create(array_merge([
            'account_id' => $account->id,
            'symbol' => 'EURUSD',
            'side' => 'BUY',
            'status' => 'OPEN',
            'volume' => '0.20',
            'entry_price' => '1.10000',
            'entry_time' => now()->subMinutes(30),
            'stop_loss' => '1.09800',
            'risk_amount' => '40',
            'unrealized_pnl' => '-15.5',
            'broker_position_id' => 'P'.Str::random(6),
            'is_simulated' => $account->isPaper(),
        ], $overrides));
    }

    protected function snapshot(TradingAccount $account, float $equity, string $at = 'now'): void
    {
        AccountSnapshot::query()->create(['account_id' => $account->id, 'taken_at' => now()->modify($at), 'balance' => $equity, 'equity' => $equity]);
    }
}
