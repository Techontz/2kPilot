<?php

namespace Tests\Feature;

use App\Models\SystemState;
use App\Services\Mfa\TwoFactorService;
use Database\Factories\UserFactory;
use Illuminate\Support\Facades\Http;
use PragmaRX\Google2FA\Google2FA;
use Tests\TestCase;

class TradingControlTest extends TestCase
{
    public function test_fresh_install_starts_with_trading_stopped(): void
    {
        $status = $this->actingAs($this->owner())->getJson('/api/trading/status')->assertOk();
        $status->assertJson([
            'kill_switch_engaged' => true,
            'trading_mode' => 'DEMO',
            'live_trading_locked' => true,
            'engine_state' => 'offline',
            'new_orders_permitted' => false,
        ]);
    }

    public function test_stop_is_idempotent_audited_and_never_closes_positions(): void
    {
        Http::fake(); // any engine call would be recorded
        $owner = $this->owner();
        $this->actingAs($owner)->postJson('/api/trading/resume', ['confirm' => true])->assertOk();
        $this->postJson('/api/trading/stop', ['reason' => 'news'])->assertOk()->assertJsonPath('kill_switch_engaged', true);
        $this->postJson('/api/trading/stop', ['reason' => 'again'])->assertOk();
        Http::assertNothingSent();
        $this->assertSame('news', SystemState::current()->kill_switch_reason);
        $this->assertDatabaseCount('audit_logs', 3);
        $this->assertDatabaseHas('notifications', ['type' => 'trading.stopped']);
    }

    public function test_resume_needs_explicit_confirmation(): void
    {
        $this->actingAs($this->owner())->postJson('/api/trading/resume')->assertStatus(422);
        $this->postJson('/api/trading/resume', ['confirm' => true])->assertOk()->assertJsonPath('kill_switch_engaged', false);
    }

    public function test_new_orders_are_permitted_only_with_a_running_engine(): void
    {
        $owner = $this->owner();
        $this->actingAs($owner)->postJson('/api/trading/resume', ['confirm' => true]);
        $this->getJson('/api/trading/status')->assertJsonPath('new_orders_permitted', false);
        $this->engineAlive();
        $this->getJson('/api/trading/status')->assertJsonPath('engine_state', 'running')->assertJsonPath('new_orders_permitted', true);
    }

    public function test_mode_can_only_change_while_stopped(): void
    {
        $owner = $this->owner();
        $this->actingAs($owner)->postJson('/api/trading/resume', ['confirm' => true]);
        $this->putJson('/api/trading/mode', ['mode' => 'BACKTEST'])->assertStatus(409)->assertJsonPath('code', 'stop_first');
        $this->postJson('/api/trading/stop');
        $this->putJson('/api/trading/mode', ['mode' => 'BACKTEST'])->assertOk()->assertJsonPath('trading_mode', 'BACKTEST');
    }

    public function test_live_is_impossible_while_the_server_lock_is_on(): void
    {
        $this->actingAs($this->owner())
            ->putJson('/api/trading/mode', ['mode' => 'LIVE', 'password' => UserFactory::PASSWORD, 'confirmation_phrase' => 'ENABLE LIVE TRADING'])
            ->assertForbidden()->assertJsonPath('code', 'live_locked');
        $this->assertSame('DEMO', SystemState::current()->trading_mode->value);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.mode.change_denied', 'outcome' => 'denied']);
    }

    public function test_live_needs_mfa_password_and_phrase_even_when_unlocked(): void
    {
        config(['fx.live_trading_enabled' => true]);
        $owner = $this->owner();
        $body = ['mode' => 'LIVE', 'password' => UserFactory::PASSWORD, 'confirmation_phrase' => 'ENABLE LIVE TRADING'];
        $this->actingAs($owner)->putJson('/api/trading/mode', $body)->assertForbidden()->assertJsonPath('code', 'mfa_required');

        $mfa = app(TwoFactorService::class);
        $secret = $mfa->begin($owner)['secret'];
        $this->assertNotNull($mfa->confirm($owner->fresh(), (new Google2FA)->getCurrentOtp($secret)));
        $owner->refresh();
        $this->actingAs($owner)->putJson('/api/trading/mode', ['password' => 'wrong'] + $body)->assertJsonPath('code', 'password_incorrect');
        $this->putJson('/api/trading/mode', ['confirmation_phrase' => 'yes'] + $body)->assertJsonPath('code', 'confirmation_required');
        $this->putJson('/api/trading/mode', $body)->assertOk()->assertJsonPath('trading_mode', 'LIVE');
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.mode.live_enabled']);
    }

    public function test_close_positions_stops_trading_first_then_asks_the_engine(): void
    {
        $this->fakeEngine(['/internal/positions/close-all' => ['closed' => 2, 'failed' => []]]);
        $owner = $this->owner();
        $this->actingAs($owner)->postJson('/api/trading/resume', ['confirm' => true]);
        $this->postJson('/api/trading/close-positions')->assertStatus(422); // confirmation required
        $this->postJson('/api/trading/close-positions', ['confirm' => true, 'reason' => 'panic'])
            ->assertOk()->assertJsonPath('closed', 2)->assertJsonPath('status.kill_switch_engaged', true);
        Http::assertSent(fn ($r) => str_ends_with($r->url(), '/internal/positions/close-all') && $r['actor_label'] === $owner->email);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.close_all_positions', 'outcome' => 'success']);
    }

    public function test_viewers_cannot_operate_trading(): void
    {
        $viewer = $this->viewer();
        $this->actingAs($viewer)->getJson('/api/trading/status')->assertOk();
        $this->postJson('/api/trading/resume', ['confirm' => true])->assertForbidden();
        $this->postJson('/api/trading/stop')->assertForbidden();
        $this->putJson('/api/trading/mode', ['mode' => 'BACKTEST'])->assertForbidden();
        $this->postJson('/api/trading/close-positions', ['confirm' => true])->assertForbidden();
    }
}
