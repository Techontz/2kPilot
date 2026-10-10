<?php

namespace App\Services\Brokers;

use App\Enums\AccountEnvironment;
use App\Enums\AuditOutcome;
use App\Enums\ConnectionStatus;
use App\Enums\ConnectorType;
use App\Exceptions\DomainException;
use App\Models\BrokerConnection;
use App\Models\Dataset;
use App\Models\Order;
use App\Models\RiskProfile;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use App\Services\Notifier;
use App\Services\Security\BrokerVault;
use App\Services\Trading\TradingControl;
use Illuminate\Support\Facades\DB;

/**
 * The Broker Center: 2kPilot → Broker Manager → Broker Adapter → Broker → Account.
 *
 * Every connection and account belongs to the user who added it.
 *
 * Laravel owns the wizard, the stored connections and the encrypted secrets.
 * The trading engine proves a connection works (test) and keeps it alive.
 *
 * Safety rules (tests/Feature/BrokersTest.php):
 *  - the BROKER's report decides the environment; a "DEMO" that is really
 *    LIVE (or unknown) is refused and nothing is saved;
 *  - adding a LIVE account needs explicit acknowledgement, and it can never
 *    trade while the server LIVE lock is on;
 *  - new accounts are saved with trading DISABLED;
 *  - secrets are encrypted before storage and never returned;
 *  - a connection is only CONNECTED after the engine connected it.
 */
class BrokerService
{
    public function __construct(
        private readonly EngineClient $engine,
        private readonly BrokerVault $vault,
        private readonly AuditLogger $audit,
        private readonly Notifier $notifier,
        private readonly TradingControl $control,
    ) {}

    /** The connector catalogue for the wizard, with setup status. */
    public function connectors(DerivOAuth $oauth): array
    {
        $out = [];
        foreach (config('brokers') as $id => $entry) {
            $status = 'available';
            $detail = null;
            if ($id === 'deriv' && ! config('tradepilot.deriv.app_id')) {
                $status = 'needs_setup';
                $detail = 'Add your Deriv App ID (DERIV_APP_ID) to backend/.env and trading-engine/.env. Register an app at developers.deriv.com.';
            }
            $methods = $entry['auth_methods'];
            if ($id === 'deriv' && ! $oauth->enabled()) {
                $methods = array_values(array_diff($methods, ['oauth']));
            }
            $out[] = [
                'id' => $id,
                'name' => $entry['name'],
                'tagline' => $entry['tagline'],
                'description' => $entry['description'],
                'environments' => $entry['environments'],
                'auth_methods' => $methods,
                'fields' => $entry['fields'],
                'status' => $status,
                'status_detail' => $detail,
            ];
        }

        return $out;
    }

    /**
     * Split submitted values into non-secret settings and secrets, using the
     * catalogue's `secret` flags. Secrets are encrypted immediately.
     * A paper "replay" may only use datasets the user can see.
     *
     * @return array{0: array<string, mixed>, 1: string|null}
     */
    public function prepare(ConnectorType $type, array $values, ?array $oauthCredentials = null, ?User $owner = null): array
    {
        $settings = [];
        $secrets = [];
        foreach (config("brokers.{$type->value}.fields") as $field) {
            $name = $field['name'];
            if (! array_key_exists($name, $values)) {
                continue;
            }
            if (! empty($field['secret'])) {
                $secrets[$name] = (string) $values[$name];
            } else {
                $settings[$name] = $values[$name];
            }
        }
        foreach (['account_id', 'multiplier', 'dataset_symbol_map', 'commission_per_lot', 'slippage_points', 'seed', 'currency'] as $extra) {
            if (array_key_exists($extra, $values)) {
                $settings[$extra] = $values[$extra];
            }
        }
        $replay = array_values((array) ($settings['dataset_symbol_map'] ?? []));
        if ($replay && ($owner === null || Dataset::query()->visibleTo($owner)->whereKey($replay)->count() !== count(array_unique($replay)))) {
            throw new DomainException('Dataset not found.', 404, 'not_found');
        }
        if ($type === ConnectorType::Deriv) {
            $secrets = $oauthCredentials ?? ['token' => (string) ($secrets['token'] ?? ''), 'token_kind' => 'pat'];
            if (($secrets['token'] ?? '') === '') {
                throw new DomainException('Sign in with Deriv or paste a personal access token first.', 422, 'deriv_token_missing');
            }
        }
        $sealed = $secrets ? $this->vault->seal($secrets) : null;

        return [$settings, $sealed];
    }

    /** Ask the engine to connect with these settings and report what the broker says. */
    public function test(ConnectorType $type, AccountEnvironment $expected, array $settings, ?string $sealed): array
    {
        return $this->engine->post('/internal/connections/test', [
            'connector_type' => $type->value,
            'expected_environment' => $expected->value,
            'settings' => (object) $settings,
            'credentials_encrypted' => $sealed,
        ], 60);
    }

    /** Deriv Options accounts reachable with a token (wizard step "choose account"). */
    public function derivAccounts(string $sealed): array
    {
        return $this->engine->post('/internal/deriv/accounts', ['credentials_encrypted' => $sealed]);
    }

    public function create(
        User $actor,
        ConnectorType $type,
        AccountEnvironment $expected,
        string $label,
        array $settings,
        ?string $sealed,
        ?string $riskProfileId,
        bool $acknowledgeLive,
    ): TradingAccount {
        if ($expected === AccountEnvironment::Live && ! $acknowledgeLive) {
            throw DomainException::forbidden('Adding a LIVE (real-money) account requires explicit acknowledgement.', 'live_ack_required');
        }
        if ($riskProfileId !== null && ! RiskProfile::query()->ownedBy($actor)->whereKey($riskProfileId)->exists()) {
            throw new DomainException('Risk profile not found.', 404, 'not_found');
        }
        try {
            $outcome = $this->test($type, $expected, $settings, $sealed); // verify again at save time
        } catch (EngineException $exception) {
            $this->audit->record('broker.add_failed', AuditOutcome::Failure, $actor, 'broker_connection',
                details: ['type' => $type->value, 'reason' => $exception->getMessage()]);
            throw $exception;
        }
        $info = $outcome['account'];
        if ($type !== ConnectorType::Paper) {
            $duplicate = TradingAccount::query()
                ->where('broker_account_id', $info['account_id'])
                ->where('server', $info['server'] ?? '')
                ->whereHas('connection', fn ($q) => $q->where('connector_type', $type->value)->where('is_enabled', true))
                ->exists();
            if ($duplicate) {
                throw DomainException::conflict('This broker account is already connected.');
            }
        }
        $label = trim($label) ?: match ($type) {
            ConnectorType::Paper => 'Paper account',
            ConnectorType::Deriv => 'Deriv '.$info['account_id'],
        };

        $account = DB::transaction(function () use ($actor, $type, $expected, $label, $outcome, $sealed, $info, $riskProfileId) {
            $connection = BrokerConnection::query()->create([
                'user_id' => $actor->id,
                'label' => mb_substr($label, 0, 120),
                'connector_type' => $type,
                'expected_environment' => $expected,
                'settings' => $outcome['normalized_settings'],
                'credentials_encrypted' => $sealed,
                'status' => ConnectionStatus::Disconnected,
                'status_detail' => 'Verified — connecting…',
            ]);
            $brokerAccountId = $type === ConnectorType::Paper
                ? 'PAPER-'.strtoupper(substr(str_replace('-', '', $connection->id), -8))
                : $info['account_id'];

            return TradingAccount::query()->create([
                'connection_id' => $connection->id,
                'user_id' => $actor->id,
                'broker_account_id' => $brokerAccountId,
                'label' => mb_substr($label, 0, 120),
                'name' => mb_substr((string) ($info['name'] ?? ''), 0, 200),
                'server' => mb_substr((string) ($info['server'] ?? ''), 0, 200),
                'currency' => $info['currency'],
                'environment' => AccountEnvironment::from($info['environment']),
                'leverage' => $info['leverage'] ?? null,
                'trading_enabled' => false, // never trades merely because it was added
                'risk_profile_id' => $riskProfileId,
                'capabilities' => $outcome['capabilities'] ?? [],
                'balance' => $info['balance'] ?? null,
                'equity' => $info['equity'] ?? null,
                'margin' => $info['margin'] ?? null,
                'free_margin' => $info['free_margin'] ?? null,
                'synced_at' => now(),
            ]);
        });

        $this->audit->record('broker.added', actor: $actor, targetType: 'broker_connection', targetId: $account->connection_id,
            details: ['type' => $type->value, 'environment' => $account->environment->value, 'account' => $account->broker_account_id]);
        $this->notifier->notify('broker.connected',
            "{$account->label} ({$account->environment->value}) verified and saved. Trading is disabled until you enable it.",
            $account->user_id, $account->id);
        if ($account->environment === AccountEnvironment::Live) { // LIVE authorisation never stretches to a new real-money account
            $this->control->revokeLiveIf($actor->id, $actor, "a new LIVE account \"{$account->label}\" was added", fn () => true);
        }
        $this->connect($account->connection, $actor, audit: false);

        return $account->fresh();
    }

    /** Connect now (after saving, or "Reconnect"). Status is written by the engine. */
    public function connect(BrokerConnection $connection, User $actor, bool $audit = true): array
    {
        $connection->forceFill(['is_enabled' => true])->save();
        try {
            $result = $this->engine->post("/internal/connections/{$connection->id}/connect", [], 60);
        } catch (EngineException $exception) {
            if ($exception->errorCode === 'engine_unreachable') {
                $connection->forceFill([
                    'status' => ConnectionStatus::Disconnected,
                    'status_detail' => 'Saved. It will connect when the trading engine is running.',
                ])->save();
            }
            if ($audit) {
                $this->audit->record('broker.reconnect', AuditOutcome::Failure, $actor, 'broker_connection', $connection->id,
                    ['reason' => $exception->getMessage()]);
            }
            throw $exception;
        }
        if ($audit) {
            $this->audit->record('broker.reconnect', actor: $actor, targetType: 'broker_connection', targetId: $connection->id);
        }

        return $result;
    }

    public function disconnect(BrokerConnection $connection, User $actor): void
    {
        $connection->forceFill(['is_enabled' => false])->save(); // the engine stops ticking it
        foreach ($connection->accounts as $account) {
            $account->forceFill(['trading_enabled' => false])->save();
        }
        try {
            $this->engine->post("/internal/connections/{$connection->id}/disconnect");
        } catch (EngineException) {
            // Engine offline: nothing is connected anyway.
        }
        $connection->forceFill(['status' => ConnectionStatus::Disconnected, 'status_detail' => 'Disconnected by '.$actor->email])->save();
        $this->audit->record('broker.disconnected', actor: $actor, targetType: 'broker_connection', targetId: $connection->id);
        $this->notifier->notify('broker.disconnected', "{$connection->label} disconnected by {$actor->email}. Trading on it is disabled.", $connection->user_id);
    }

    /** Remove a connection. With trading history it is archived instead (history is never erased). */
    public function delete(BrokerConnection $connection, User $actor): string
    {
        $accountIds = $connection->accounts()->pluck('id');
        if (Trade::query()->whereIn('account_id', $accountIds)->where('status', 'OPEN')->exists()) {
            throw DomainException::conflict('Close all open positions on this account before removing it.');
        }
        try {
            $this->engine->post("/internal/connections/{$connection->id}/disconnect");
        } catch (EngineException) {
            // offline engine: nothing to release
        }
        $hasHistory = Trade::query()->whereIn('account_id', $accountIds)->exists()
            || Order::query()->whereIn('account_id', $accountIds)->exists();
        if ($hasHistory) {
            DB::transaction(function () use ($connection) {
                $connection->forceFill([
                    'is_enabled' => false,
                    'credentials_encrypted' => null, // secrets are wiped
                    'status' => ConnectionStatus::Disconnected,
                    'status_detail' => 'Archived — trading history kept, credentials deleted',
                ])->save();
                $connection->accounts()->update(['trading_enabled' => false]);
            });
            $action = 'broker.archived';
        } else {
            $connection->delete();
            $action = 'broker.removed';
        }
        $this->audit->record($action, actor: $actor, targetType: 'broker_connection', targetId: $connection->id,
            details: ['label' => $connection->label]);

        return $action;
    }

    /** Label, risk profile and the "Trading enabled" switch of an account. */
    public function updateAccount(TradingAccount $account, User $actor, array $changes): TradingAccount
    {
        $applied = [];
        $profileChanged = false;
        if (array_key_exists('label', $changes) && trim((string) $changes['label']) !== '') {
            $account->label = mb_substr(trim($changes['label']), 0, 120);
            $applied['label'] = $account->label;
        }
        if (array_key_exists('risk_profile_id', $changes)) {
            if ($changes['risk_profile_id'] !== null && ! RiskProfile::query()->whereKey($changes['risk_profile_id'])->where('user_id', $account->user_id)->exists()) {
                throw new DomainException('Risk profile not found.', 404, 'not_found');
            }
            $profileChanged = $account->risk_profile_id !== $changes['risk_profile_id'];
            $account->risk_profile_id = $changes['risk_profile_id'];
            $applied['risk_profile_id'] = $changes['risk_profile_id'];
        }
        if (array_key_exists('trading_enabled', $changes) && (bool) $changes['trading_enabled'] !== $account->trading_enabled) {
            if ($changes['trading_enabled']) {
                $problem = $this->enableProblem($account);
                if ($problem !== null) {
                    $this->audit->record('account.trading_enable_denied', AuditOutcome::Denied, $actor, 'trading_account', $account->id,
                        ['reason' => $problem]);
                    throw DomainException::forbidden($problem, 'trading_enable_denied');
                }
            }
            $account->trading_enabled = (bool) $changes['trading_enabled'];
            $applied['trading_enabled'] = $account->trading_enabled;
        }
        if ($account->risk_profile_id === null && $account->trading_enabled) {
            $account->trading_enabled = false; // never trade without a risk profile
            $applied['trading_enabled'] = false;
        }
        $account->save();
        if ($applied) {
            $this->audit->record('account.updated', actor: $actor, targetType: 'trading_account', targetId: $account->id, details: $applied);
        }
        if ($profileChanged) {
            $this->control->revokeLiveIf($account->user_id, $actor, "the risk profile of \"{$account->label}\" was changed",
                fn ($state) => $state->live_authorized_account_id === $account->id);
        }
        if (($applied['trading_enabled'] ?? false) === true) {
            $this->control->accountTradingEnabled($account, $actor);
        }

        return $account;
    }

    public function enableProblem(TradingAccount $account): ?string
    {
        $connection = $account->connection;

        return match (true) {
            $account->risk_profile_id === null => 'Assign a risk profile before enabling trading.',
            $account->environment === AccountEnvironment::Unknown => 'Accounts of unknown type (demo/live) can never trade.',
            $account->environment === AccountEnvironment::Live && ! config('tradepilot.live_trading_enabled') => 'LIVE trading is locked on this server (LIVE_TRADING_ENABLED=false).',
            $connection !== null && ! $connection->is_enabled => 'Reconnect this broker before enabling trading.',
            default => null,
        };
    }
}
