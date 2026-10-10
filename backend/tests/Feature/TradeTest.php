<?php

namespace Tests\Feature;

use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class TradeTest extends TestCase
{
    use CreatesTradingData;

    private function ticket(string $accountId, array $extra = []): array
    {
        return array_merge([
            'account_id' => $accountId, 'symbol' => 'EURUSD', 'side' => 'BUY', 'volume' => '0.10',
            'stop_loss' => '1.09800', 'take_profit' => '1.10400',
            'idempotency_key' => 'ticket-0123456789abcdef', 'confirm' => true,
        ], $extra);
    }

    public function test_preview_runs_the_engine_risk_check(): void
    {
        $this->fakeEngine(['/internal/orders/preview' => ['approved' => true, 'checks' => [['rule' => 'Kill switch', 'passed' => true, 'detail' => 'released']], 'risk_amount' => '20']]);
        $account = $this->account();
        $this->actingAs($this->me())->postJson('/api/trade/preview', $this->ticket($account->id, ['volume' => null, 'idempotency_key' => null, 'confirm' => null]))
            ->assertOk()->assertJsonPath('approved', true);
        Http::assertSent(fn (Request $r) => str_ends_with($r->url(), '/internal/orders/preview') && ! isset($r['volume']));
    }

    public function test_a_stop_loss_is_always_required(): void
    {
        Http::fake();
        $account = $this->account();
        $this->actingAs($this->me())->postJson('/api/trade/orders', $this->ticket($account->id, ['stop_loss' => null]))
            ->assertStatus(422)->assertJsonValidationErrors('stop_loss');
        Http::assertNothingSent();
    }

    public function test_submit_needs_confirmation_and_an_idempotency_key(): void
    {
        Http::fake();
        $account = $this->account();
        $owner = $this->me();
        $this->actingAs($owner)->postJson('/api/trade/orders', $this->ticket($account->id, ['confirm' => false]))->assertJsonValidationErrors('confirm');
        $this->postJson('/api/trade/orders', $this->ticket($account->id, ['idempotency_key' => null]))->assertJsonValidationErrors('idempotency_key');
        Http::assertNothingSent();
    }

    public function test_submit_forwards_actor_and_key_and_audits_the_outcome(): void
    {
        $this->fakeEngine(['/internal/orders' => ['signal_id' => 's1', 'status' => 'REJECTED', 'rejection_reason' => 'Trade rejected: Kill switch: STOP ALL TRADING is engaged', 'order' => null, 'trade_id' => null]]);
        $account = $this->account();
        $owner = $this->me();
        $this->actingAs($owner)->postJson('/api/trade/orders', $this->ticket($account->id))
            ->assertOk()->assertJsonPath('status', 'REJECTED');
        Http::assertSent(fn (Request $r) => $r['idempotency_key'] === 'ticket-0123456789abcdef' && $r['actor_id'] === $owner->id && $r['actor_label'] === $owner->email);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trade.manual_ticket', 'outcome' => 'denied', 'target_id' => $account->id]);
    }

    public function test_positions_close_and_modify_go_through_the_engine(): void
    {
        $this->fakeEngine(['/internal/positions/' => fn (Request $r) => Http::response($r->method() === 'PUT'
            ? ['stop_loss' => '1.099', 'take_profit' => null] : ['order_status' => 'FILLED', 'fill_price' => '1.1003'])]);
        $account = $this->account();
        $trade = $this->openTrade($account);
        $owner = $this->me();
        $this->actingAs($owner)->getJson('/api/positions')->assertOk()->assertJsonPath('0.id', $trade->id)->assertJsonPath('0.is_simulated', true);
        $this->putJson("/api/positions/{$trade->id}", ['take_profit' => '1.2'])->assertJsonValidationErrors('stop_loss'); // a stop can't be removed
        $this->putJson("/api/positions/{$trade->id}", ['stop_loss' => '1.09900'])->assertOk();
        $this->postJson("/api/positions/{$trade->id}/close")->assertStatus(422);
        $this->postJson("/api/positions/{$trade->id}/close", ['confirm' => true])->assertOk()->assertJsonPath('order_status', 'FILLED');
        $this->assertDatabaseHas('audit_logs', ['action' => 'position.closed_manually', 'target_id' => $trade->id]);
        $this->assertDatabaseHas('audit_logs', ['action' => 'position.modified_manually', 'target_id' => $trade->id]);
    }

    public function test_engine_refusals_are_relayed(): void
    {
        $this->fakeEngine(['/internal/orders' => Http::response(['error' => ['code' => 'conflict', 'message' => 'An earlier order on this account is still being reconciled with the broker.']], 409)]);
        $account = $this->account();
        $this->actingAs($this->me())->postJson('/api/trade/orders', $this->ticket($account->id))
            ->assertStatus(409)->assertJsonPath('message', 'An earlier order on this account is still being reconciled with the broker.');
    }
}
