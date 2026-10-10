<?php

namespace Tests\Feature;

use App\Models\SystemState;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

/**
 * The dashboard keeps three things apart: is the engine's HTTP API healthy, is its
 * trading supervisor on and beating, and may new orders be placed. A healthy HTTP
 * answer never turns trading on.
 */
class EngineHealthTest extends TestCase
{
    private function health(bool $supervisorEnabled = true): array
    {
        return ['status' => 'ok', 'version' => '1.0.0', 'database' => 'ok', 'engine_enabled' => $supervisorEnabled,
            'engine_leader' => $supervisorEnabled, 'engine_heartbeat_at' => null, 'live_trading_enabled' => false];
    }

    private function resumed(): void
    {
        $this->actingAs($this->me())->postJson('/api/trading/resume', ['confirm' => true])->assertOk();
    }

    public function test_api_online_with_the_supervisor_disabled_is_not_reported_offline(): void
    {
        $this->fakeEngine(['/internal/health' => $this->health(supervisorEnabled: false)]);

        $status = $this->actingAs($this->me())->getJson('/api/system/status')->assertOk();
        $status->assertJsonPath('engine_service.status', 'online')
            ->assertJsonPath('engine_service.reachable', true)
            ->assertJsonPath('engine_service.supervisor_enabled', false)
            ->assertJsonPath('engine_supervisor.state', 'disabled')
            ->assertJsonPath('engine_summary.code', 'trading_disabled')
            ->assertJsonPath('engine_summary.label', 'Engine online — automated trading disabled')
            ->assertJsonPath('engine_summary.trading_active', false)
            // Unchanged, heartbeat-based permission: still nothing may trade.
            ->assertJsonPath('trading.engine_state', 'offline')
            ->assertJsonPath('trading.new_orders_permitted', false);
        $this->assertStringNotContainsString('make dev', $status->getContent());
    }

    public function test_supervisor_running_with_a_fresh_heartbeat(): void
    {
        $this->fakeEngine(['/internal/health' => $this->health()]);
        $this->engineAlive();
        $this->resumed();

        $this->actingAs($this->me())->getJson('/api/trading/status')->assertOk()
            ->assertJsonPath('engine_service.status', 'online')
            ->assertJsonPath('engine_supervisor.state', 'running')
            ->assertJsonPath('engine_summary.code', 'running')
            ->assertJsonPath('engine_summary.trading_active', true)
            ->assertJsonPath('engine_state', 'running')
            ->assertJsonPath('new_orders_permitted', true);
    }

    public function test_a_stale_heartbeat_is_a_warning_and_blocks_new_orders(): void
    {
        $this->fakeEngine(['/internal/health' => $this->health()]);
        SystemState::query()->whereKey(1)->update(['engine_heartbeat_at' => now()->subMinutes(5)]);
        $this->resumed();

        $this->actingAs($this->me())->getJson('/api/trading/status')->assertOk()
            ->assertJsonPath('engine_service.status', 'online')
            ->assertJsonPath('engine_supervisor.state', 'stale')
            ->assertJsonPath('engine_summary.code', 'supervisor_stale')
            ->assertJsonPath('engine_summary.tone', 'warning')
            ->assertJsonPath('engine_summary.label', 'Trading supervisor not responding')
            ->assertJsonPath('new_orders_permitted', false);
    }

    public function test_supervisor_enabled_without_any_heartbeat_yet(): void
    {
        $this->fakeEngine(['/internal/health' => $this->health()]);

        $this->actingAs($this->me())->getJson('/api/trading/status')->assertOk()
            ->assertJsonPath('engine_supervisor.state', 'not_started')
            ->assertJsonPath('engine_summary.code', 'supervisor_not_started')
            ->assertJsonPath('engine_summary.tone', 'warning')
            ->assertJsonPath('new_orders_permitted', false);
    }

    public function test_engine_offline_only_when_the_api_is_unreachable(): void
    {
        $this->engineDown();
        $this->engineAlive(); // even with a (leftover) fresh heartbeat in the database

        $this->actingAs($this->me())->getJson('/api/system/status')->assertOk()
            ->assertJsonPath('engine_service.status', 'unreachable')
            ->assertJsonPath('engine_service.reachable', false)
            ->assertJsonPath('engine_supervisor.state', 'unknown')
            ->assertJsonPath('engine_summary.code', 'engine_offline')
            ->assertJsonPath('engine_summary.label', 'Engine offline')
            ->assertJsonPath('engine_summary.tone', 'error');
    }

    public function test_an_unhealthy_answer_is_an_error_not_offline(): void
    {
        $this->fakeEngine(['/internal/health' => Http::response(['error' => ['code' => 'database', 'message' => 'db down']], 500)]);

        $this->actingAs($this->me())->getJson('/api/trading/status')->assertOk()
            ->assertJsonPath('engine_service.status', 'error')
            ->assertJsonPath('engine_service.reachable', true)
            ->assertJsonPath('engine_summary.code', 'engine_error');
    }

    public function test_the_health_check_is_cached_across_polls(): void
    {
        $this->fakeEngine(['/internal/health' => $this->health()]);
        foreach (range(1, 3) as $_) {
            $this->actingAs($this->me())->getJson('/api/trading/status')->assertOk();
        }
        Http::assertSentCount(1);
    }

    public function test_stop_never_waits_on_an_engine_health_check(): void
    {
        $this->engineDown();
        $this->actingAs($this->me())->postJson('/api/trading/stop')->assertOk()
            ->assertJsonPath('kill_switch_engaged', true)
            ->assertJsonPath('engine_service', null); // nothing cached yet, nothing called
        Http::assertNotSent(fn (Request $r) => str_contains($r->url(), '/internal/health'));
    }

    public function test_status_fields_are_additive(): void
    {
        $this->fakeEngine(['/internal/health' => $this->health()]);
        $this->actingAs($this->me())->getJson('/api/system/status')->assertOk()
            ->assertJsonStructure(['app', 'environment', 'database', 'trading' => ['engine_state', 'engine_detail', 'new_orders_permitted'],
                'engine', 'live_trading_enabled', 'engine_service', 'engine_supervisor', 'engine_summary']);
    }
}
