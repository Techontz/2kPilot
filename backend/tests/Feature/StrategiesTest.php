<?php

namespace Tests\Feature;

use App\Models\StrategyAssignment;
use App\Models\StrategyEvaluation;
use Illuminate\Support\Facades\Http;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class StrategiesTest extends TestCase
{
    use CreatesTradingData;

    public function test_new_versions_are_validated_by_the_engine_and_immutable(): void
    {
        $this->fakeEngine([
            '/internal/strategies/trend_pullback/validate' => ['parameters' => ['ema_fast' => 20, 'ema_slow' => 200], 'code_version' => '1.0.0'],
            '/internal/strategies' => [],
        ]);
        $v1 = $this->strategyVersion();
        $response = $this->actingAs($this->owner())->postJson("/api/strategies/{$v1->strategy_id}/versions", ['parameters' => ['ema_fast' => 20], 'notes' => 'faster'])
            ->assertCreated()->assertJsonPath('version', 2)->assertJsonPath('parameters.ema_fast', 20);
        $this->assertSame(50, $v1->fresh()->parameters['ema_fast'], 'version 1 is untouched');
        $this->assertDatabaseHas('audit_logs', ['action' => 'strategy.version_created']);
        $this->getJson('/api/strategies')->assertOk()->assertJsonCount(2, '0.versions');
        $this->assertNotNull($response->json('id'));
    }

    public function test_invalid_parameters_are_rejected(): void
    {
        $this->fakeEngine(['/internal/strategies/trend_pullback/validate' => Http::response(['error' => ['code' => 'invalid_strategy_config', 'message' => 'Invalid parameters: ema_fast must be < ema_slow']], 422)]);
        $v1 = $this->strategyVersion();
        $this->actingAs($this->owner())->postJson("/api/strategies/{$v1->strategy_id}/versions", ['parameters' => ['ema_fast' => 400]])
            ->assertStatus(422)->assertJsonPath('code', 'invalid_strategy_config');
    }

    public function test_assignments_start_paused_and_need_a_risk_profile_to_enable(): void
    {
        $version = $this->strategyVersion();
        $account = $this->account();
        $owner = $this->owner();
        $assignment = $this->actingAs($owner)->postJson('/api/assignments', ['strategy_version_id' => $version->id, 'account_id' => $account->id, 'symbol' => 'EURUSD'])
            ->assertCreated()->assertJsonPath('status', 'PAUSED')->json();
        $this->postJson('/api/assignments', ['strategy_version_id' => $version->id, 'account_id' => $account->id, 'symbol' => 'EURUSD'])->assertStatus(409);
        $this->postJson("/api/assignments/{$assignment['id']}/enable")->assertForbidden()->assertJsonPath('code', 'risk_profile_required');
        $account->update(['risk_profile_id' => $this->defaultProfile()->id]);
        $this->postJson("/api/assignments/{$assignment['id']}/enable")->assertOk()->assertJsonPath('status', 'ENABLED');
        $this->postJson("/api/assignments/{$assignment['id']}/pause", ['reason' => 'news week'])->assertOk()->assertJsonPath('status_reason', 'news week');
        $this->assertDatabaseHas('notifications', ['type' => 'strategy.paused']);
    }

    public function test_switching_versions_pauses_the_assignment(): void
    {
        $v1 = $this->strategyVersion();
        $v2 = $v1->replicate()->fill(['version' => 2]);
        $v2->save();
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id]);
        $assignment = StrategyAssignment::query()->create(['strategy_id' => $v1->strategy_id, 'strategy_version_id' => $v1->id, 'account_id' => $account->id, 'symbol' => 'EURUSD', 'status' => 'ENABLED']);
        $this->actingAs($this->owner())->putJson("/api/assignments/{$assignment->id}/version", ['strategy_version_id' => $v2->id])
            ->assertOk()->assertJsonPath('status', 'PAUSED')->assertJsonPath('version', 2);
    }

    public function test_evaluations_explain_every_bar(): void
    {
        $version = $this->strategyVersion();
        $account = $this->account();
        $assignment = StrategyAssignment::query()->create(['strategy_id' => $version->strategy_id, 'strategy_version_id' => $version->id, 'account_id' => $account->id, 'symbol' => 'EURUSD']);
        StrategyEvaluation::query()->create(['assignment_id' => $assignment->id, 'bar_time' => now()->subHour(), 'outcome' => 'NO_SETUP', 'summary' => 'No pullback yet', 'checks' => [['name' => 'Trend', 'passed' => true, 'detail' => 'up']]]);
        $this->actingAs($this->viewer())->getJson("/api/assignments/{$assignment->id}/evaluations")
            ->assertOk()->assertJsonPath('evaluations.data.0.summary', 'No pullback yet')->assertJsonPath('evaluations.data.0.checks.0.name', 'Trend');
    }
}
