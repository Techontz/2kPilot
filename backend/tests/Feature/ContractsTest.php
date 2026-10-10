<?php

namespace Tests\Feature;

use App\Enums\ConnectorType;
use App\Models\StrategyAssignment;
use App\Models\TradingAccount;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Testing\TestResponse;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

/** Contract-aware trading: assignments, manual tickets and the broker's contract offer. */
class ContractsTest extends TestCase
{
    use CreatesTradingData;

    private function deriv(array $overrides = [], $owner = null): TradingAccount
    {
        return $this->account($overrides, ConnectorType::Deriv, $owner);
    }

    private function assign(TradingAccount $account, array $contract = []): TestResponse
    {
        return $this->actingAs($this->me())->postJson('/api/assignments', [
            'strategy_version_id' => $this->strategyVersion()->id, 'account_id' => $account->id, 'symbol' => 'R_100',
        ] + $contract);
    }

    /** The engine echoes the contract back, as it does after checking it against contracts_for. */
    private function engineAcceptsContracts(): void
    {
        $this->fakeEngine(['/internal/accounts/' => fn (Request $r) => Http::response(['ok' => true, 'contract' => $r['contract']])]);
    }

    public function test_deriv_assignments_default_to_rise_fall_five_minutes_checked_by_the_engine(): void
    {
        $this->engineAcceptsContracts();
        $account = $this->deriv();
        $this->assign($account)->assertCreated()
            ->assertJsonPath('status', 'PAUSED')
            ->assertJsonPath('account.connector_type', 'deriv')
            ->assertJsonPath('contract', [
                'contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm', 'allow_equals' => false,
                'stake' => null, 'multiplier' => null, 'take_profit_amount' => null, 'stop_loss_amount' => null,
            ])
            ->assertJsonPath('contract_check.verified', true);
        Http::assertSent(fn (Request $r) => str_ends_with($r->url(), "/internal/accounts/{$account->id}/contracts/validate")
            && $r['symbol'] === 'R_100' && $r['contract']['contract_family'] === 'RISE_FALL' && $r['contract']['duration'] === 5);
        $this->assertDatabaseHas('strategy_assignments', ['account_id' => $account->id, 'contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm']);
    }

    public function test_paper_assignments_default_to_spot_without_asking_the_engine(): void
    {
        Http::fake();
        $this->assign($this->account())->assertCreated()
            ->assertJsonPath('contract.contract_family', 'SPOT')->assertJsonPath('contract.stake', null)
            ->assertJsonPath('account.connector_type', 'paper')->assertJsonPath('contract_check', null);
        Http::assertNothingSent();
    }

    public function test_multiplier_assignments_keep_their_settings(): void
    {
        $this->engineAcceptsContracts();
        $this->assign($this->deriv(), ['contract_family' => 'MULTIPLIER', 'multiplier' => 100, 'stake' => 10, 'take_profit_amount' => 5, 'stop_loss_amount' => 4])
            ->assertCreated()
            ->assertJsonPath('contract.contract_family', 'MULTIPLIER')->assertJsonPath('contract.multiplier', 100)
            ->assertJsonPath('contract.stake', '10.00')->assertJsonPath('contract.stop_loss_amount', '4.00')
            ->assertJsonPath('contract.duration', null);
    }

    public function test_contract_combinations_are_validated(): void
    {
        Http::fake();
        $deriv = $this->deriv();
        $this->assign($deriv, ['contract_family' => 'SPOT'])->assertStatus(422)
            ->assertJsonPath('errors.contract_family.0', 'Deriv accounts trade contracts: choose Rise/Fall or Multiplier.');
        $this->assign($deriv, ['contract_family' => 'RISE_FALL'])->assertJsonValidationErrors(['duration', 'duration_unit']);
        $this->assign($deriv, ['contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm', 'multiplier' => 10])->assertJsonValidationErrors('multiplier');
        $this->assign($deriv, ['contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'w'])->assertJsonValidationErrors('duration_unit');
        $this->assign($deriv, ['contract_family' => 'RISE_FALL', 'duration' => 0, 'duration_unit' => 'm'])->assertJsonValidationErrors('duration');
        $this->assign($deriv, ['contract_family' => 'MULTIPLIER'])->assertJsonValidationErrors('multiplier');
        $this->assign($deriv, ['contract_family' => 'MULTIPLIER', 'multiplier' => 6000])->assertJsonValidationErrors('multiplier');
        $this->assign($deriv, ['contract_family' => 'MULTIPLIER', 'multiplier' => 10, 'duration' => 5, 'duration_unit' => 'm'])->assertJsonValidationErrors(['duration', 'duration_unit']);
        $this->assign($deriv, ['contract_family' => 'MULTIPLIER', 'multiplier' => 10, 'allow_equals' => true])->assertJsonValidationErrors('allow_equals');
        $this->assign($deriv, ['contract_family' => 'MULTIPLIER', 'multiplier' => 10, 'stake' => 5, 'stop_loss_amount' => 6])->assertJsonValidationErrors('stop_loss_amount');
        $this->assign($deriv, ['contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm', 'stake' => 0])->assertJsonValidationErrors('stake');
        $this->assign($deriv, ['contract_family' => 'OPTIONS'])->assertJsonValidationErrors('contract_family');
        $this->assign($this->account(), ['contract_family' => 'SPOT', 'stake' => 5])->assertJsonValidationErrors('stake');
        Http::assertNothingSent();
        $this->assertSame(0, StrategyAssignment::query()->count());
    }

    public function test_a_contract_the_broker_does_not_offer_is_a_validation_error(): void
    {
        $this->fakeEngine(['/internal/accounts/' => Http::response(['error' => ['code' => 'contract_unavailable', 'message' => 'Rise/Fall on R_100 needs a duration of at least 1 tick and at most 365 days.']], 422)]);
        $this->assign($this->deriv(), ['contract_family' => 'RISE_FALL', 'duration' => 400, 'duration_unit' => 'd'])
            ->assertStatus(422)->assertJsonPath('errors.contract_family.0', 'Rise/Fall on R_100 needs a duration of at least 1 tick and at most 365 days.');
        $this->assertSame(0, StrategyAssignment::query()->count());
    }

    public function test_assignments_are_saved_unverified_when_the_engine_is_down(): void
    {
        $this->engineDown();
        $this->assign($this->deriv())->assertCreated()->assertJsonPath('status', 'PAUSED')
            ->assertJsonPath('contract.contract_family', 'RISE_FALL')
            ->assertJsonPath('contract_check.verified', false)
            ->assertJsonPath('contract_check.detail', 'The trading engine is not reachable right now. Please try again in a moment.');
    }

    public function test_changing_the_contract_pauses_the_assignment(): void
    {
        $this->engineAcceptsContracts();
        $version = $this->strategyVersion();
        $account = $this->deriv(['risk_profile_id' => $this->defaultProfile()->id]);
        $assignment = StrategyAssignment::query()->create(['strategy_id' => $version->strategy_id, 'strategy_version_id' => $version->id, 'account_id' => $account->id,
            'symbol' => 'R_100', 'status' => 'ENABLED', 'contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm']);
        $this->actingAs($this->me())->putJson("/api/assignments/{$assignment->id}/contract", ['contract_family' => 'MULTIPLIER', 'multiplier' => 50])
            ->assertOk()->assertJsonPath('status', 'PAUSED')
            ->assertJsonPath('status_reason', 'Contract settings changed — enable it again to trade')
            ->assertJsonPath('contract.contract_family', 'MULTIPLIER')->assertJsonPath('contract.multiplier', 50)
            ->assertJsonPath('contract.duration', null)->assertJsonPath('contract_check.verified', true);
        $this->assertDatabaseHas('strategy_assignments', ['id' => $assignment->id, 'contract_family' => 'MULTIPLIER', 'duration' => null, 'duration_unit' => null]);
        $this->assertDatabaseHas('audit_logs', ['action' => 'strategy.contract_changed', 'target_id' => $assignment->id]);
        $this->putJson("/api/assignments/{$assignment->id}/contract", ['contract_family' => 'SPOT'])->assertJsonValidationErrors('contract_family');
    }

    public function test_other_users_assignments_and_accounts_are_off_limits(): void
    {
        Http::fake();
        $other = $this->user();
        $version = $this->strategyVersion();
        $theirs = $this->deriv([], $other);
        $assignment = StrategyAssignment::query()->create(['strategy_id' => $version->strategy_id, 'strategy_version_id' => $version->id, 'account_id' => $theirs->id,
            'symbol' => 'R_100', 'contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm']);
        $this->actingAs($this->me())->putJson("/api/assignments/{$assignment->id}/contract", ['contract_family' => 'MULTIPLIER', 'multiplier' => 50])->assertForbidden();
        $this->assign($theirs)->assertNotFound();
        $this->getJson("/api/markets/contracts?account_id={$theirs->id}&symbol=R_100")->assertNotFound();
        Http::assertNothingSent();
        $this->assertSame('RISE_FALL', $assignment->fresh()->contract_family);
    }

    public function test_strategy_listing_shows_each_assignments_contract(): void
    {
        $this->fakeEngine(['/internal/strategies' => []]);
        $version = $this->strategyVersion();
        $account = $this->deriv();
        StrategyAssignment::query()->create(['strategy_id' => $version->strategy_id, 'strategy_version_id' => $version->id, 'account_id' => $account->id,
            'symbol' => 'R_100', 'contract_family' => 'RISE_FALL', 'duration' => 3, 'duration_unit' => 't', 'allow_equals' => true, 'stake' => '2.50']);
        $row = collect($this->actingAs($this->me())->getJson('/api/strategies')->assertOk()->json())->firstWhere('id', $version->strategy_id);
        $this->assertSame(['contract_family' => 'RISE_FALL', 'duration' => 3, 'duration_unit' => 't', 'allow_equals' => true, 'stake' => '2.50',
            'multiplier' => null, 'take_profit_amount' => null, 'stop_loss_amount' => null], $row['assignments'][0]['contract']);
        $this->assertSame('deriv', $row['assignments'][0]['account']['connector_type']);
    }

    public function test_deriv_tickets_default_to_rise_fall_and_need_no_stop_loss(): void
    {
        $this->fakeEngine(['/internal/orders/preview' => ['approved' => true, 'checks' => []]]);
        $account = $this->deriv();
        $this->actingAs($this->me())->postJson('/api/trade/preview', ['account_id' => $account->id, 'symbol' => 'R_100', 'side' => 'BUY'])->assertOk();
        Http::assertSent(fn (Request $r) => $r['contract']['contract_family'] === 'RISE_FALL' && $r['contract']['duration'] === 5
            && $r['contract']['duration_unit'] === 'm' && ! isset($r['stop_loss']) && ! isset($r['volume']));
    }

    public function test_ticket_contracts_are_validated_and_forwarded(): void
    {
        $this->fakeEngine(['/internal/orders' => ['signal_id' => 's1', 'status' => 'EXECUTED', 'order' => null, 'trade_id' => 't1']]);
        $account = $this->deriv();
        $ticket = ['account_id' => $account->id, 'symbol' => 'R_100', 'side' => 'SELL', 'idempotency_key' => 'ticket-0123456789abcdef', 'confirm' => true];
        $this->actingAs($this->me())->postJson('/api/trade/orders', $ticket + ['contract' => ['contract_family' => 'SPOT']])
            ->assertJsonValidationErrors('contract.contract_family');
        $this->postJson('/api/trade/orders', $ticket + ['contract' => ['duration' => 5]])->assertJsonValidationErrors('contract.contract_family');
        $this->postJson('/api/trade/orders', $ticket + ['contract' => ['contract_family' => 'RISE_FALL', 'duration' => 5]])->assertJsonValidationErrors('contract.duration_unit');
        $this->postJson('/api/trade/orders', $ticket + ['contract' => ['contract_family' => 'MULTIPLIER', 'multiplier' => 200, 'stake' => '3', 'take_profit_amount' => '2']])
            ->assertOk()->assertJsonPath('status', 'EXECUTED');
        Http::assertSentCount(1);
        Http::assertSent(fn (Request $r) => $r['contract'] === ['contract_family' => 'MULTIPLIER', 'duration' => null, 'duration_unit' => null, 'allow_equals' => false,
            'stake' => '3.00', 'multiplier' => 200, 'take_profit_amount' => '2.00', 'stop_loss_amount' => null] && ! isset($r['stop_loss']));
        $this->assertDatabaseHas('audit_logs', ['action' => 'trade.manual_ticket', 'outcome' => 'success', 'target_id' => $account->id]);
    }

    public function test_paper_tickets_may_trade_paper_contracts(): void
    {
        $this->fakeEngine(['/internal/orders/preview' => ['approved' => true, 'checks' => []]]);
        $account = $this->account();
        $this->actingAs($this->me())->postJson('/api/trade/preview', ['account_id' => $account->id, 'symbol' => 'EURUSD', 'side' => 'BUY',
            'contract' => ['contract_family' => 'RISE_FALL', 'duration' => 1, 'duration_unit' => 'h', 'allow_equals' => true]])->assertOk();
        Http::assertSent(fn (Request $r) => $r['contract']['contract_family'] === 'RISE_FALL' && $r['contract']['allow_equals'] === true);
    }

    public function test_the_contract_offer_is_proxied_from_the_engine(): void
    {
        $offer = [
            'symbol' => 'R_100', 'simulated' => false, 'market_open' => true, 'trading_suspended' => false,
            'families' => [
                'RISE_FALL' => ['available' => true, 'contract_types' => ['CALL', 'PUT', 'CALLE', 'PUTE'], 'allow_equals' => true,
                    'durations' => [['expiry_type' => 'tick', 'min' => '1t', 'max' => '10t'], ['expiry_type' => 'intraday', 'min' => '15s', 'max' => '1d']]],
                'MULTIPLIER' => ['available' => true, 'contract_types' => ['MULTUP', 'MULTDOWN'], 'multipliers' => [40, 100, 200]],
                'SPOT' => ['available' => false],
            ],
            'default_contract' => ['contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm'],
            'notes' => ['Payouts are quoted by Deriv when the contract is bought.'],
            'fetched_at' => '2026-10-10T12:00:00+00:00',
        ];
        $this->fakeEngine(['/internal/accounts/' => $offer]);
        $account = $this->deriv(['label' => 'Deriv demo']);
        $this->actingAs($this->me())->getJson("/api/markets/contracts?account_id={$account->id}&symbol=R_100")->assertOk()
            ->assertJsonPath('account.label', 'Deriv demo')->assertJsonPath('account.environment', 'DEMO')
            ->assertJsonPath('provider', 'Deriv')
            ->assertJsonPath('families.MULTIPLIER.multipliers', [40, 100, 200])
            ->assertJsonPath('families.RISE_FALL.durations.0.expiry_type', 'tick')
            ->assertJsonPath('default_contract.duration_unit', 'm');
        Http::assertSent(fn (Request $r) => str_contains($r->url(), "/internal/accounts/{$account->id}/contracts?symbol=R_100"));
        $this->getJson("/api/markets/contracts?account_id={$account->id}")->assertJsonValidationErrors('symbol');
        $this->getJson('/api/markets/contracts?account_id=nope&symbol=R_100')->assertJsonValidationErrors('account_id');
    }
}
