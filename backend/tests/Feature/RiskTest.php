<?php

namespace Tests\Feature;

use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class RiskTest extends TestCase
{
    use CreatesTradingData;

    private function limits(array $overrides = []): array
    {
        return array_merge([
            'name' => 'Careful', 'risk_per_trade_pct' => 0.5, 'max_daily_loss_pct' => 2, 'max_weekly_loss_pct' => 4,
            'max_drawdown_pct' => 10, 'max_open_positions' => 3, 'allowed_sessions' => ['LONDON'], 'max_data_age_seconds' => 120,
            'min_stop_pips' => 8, 'max_stop_pips' => 150,
        ], $overrides);
    }

    public function test_default_profile_exists_from_the_migrations(): void
    {
        $this->actingAs($this->owner())->getJson('/api/risk/profiles')->assertOk()
            ->assertJsonPath('0.name', 'Conservative (default)')->assertJsonPath('0.risk_per_trade_pct', '0.500');
    }

    public function test_profiles_are_validated_like_the_engine_does(): void
    {
        $owner = $this->owner();
        $this->actingAs($owner)->postJson('/api/risk/profiles', $this->limits(['risk_per_trade_pct' => 50]))->assertJsonValidationErrors('risk_per_trade_pct');
        $this->postJson('/api/risk/profiles', $this->limits(['min_stop_pips' => 200]))->assertJsonValidationErrors('min_stop_pips');
        $this->postJson('/api/risk/profiles', $this->limits(['allowed_sessions' => ['MOON']]))->assertJsonValidationErrors('allowed_sessions.0');
        $this->postJson('/api/risk/profiles', $this->limits(['trading_hours_start' => '08:00']))->assertJsonValidationErrors('trading_hours_end');
        $this->postJson('/api/risk/profiles', $this->limits(['cooldown_after_losses' => 3]))->assertJsonValidationErrors('cooldown_minutes');
        $this->postJson('/api/risk/profiles', $this->limits(['max_data_age_seconds' => null]))->assertJsonValidationErrors('max_data_age_seconds');
        $created = $this->postJson('/api/risk/profiles', $this->limits(['trading_hours_start' => '07:00', 'trading_hours_end' => '16:00', 'max_symbol_exposure_lots' => 0.5]))
            ->assertCreated()->json();
        $this->putJson("/api/risk/profiles/{$created['id']}", $this->limits(['max_daily_loss_pct' => 1.5]))->assertOk()->assertJsonPath('max_daily_loss_pct', '1.500');
        $this->assertDatabaseHas('audit_logs', ['action' => 'risk.profile_updated']);
    }

    public function test_profiles_in_use_and_the_default_cannot_be_deleted(): void
    {
        $owner = $this->owner();
        $this->actingAs($owner)->deleteJson("/api/risk/profiles/{$this->defaultProfile()->id}")->assertStatus(409);
        $profile = $this->postJson('/api/risk/profiles', $this->limits())->json();
        $this->account(['risk_profile_id' => $profile['id']]);
        $this->deleteJson("/api/risk/profiles/{$profile['id']}")->assertStatus(409);
    }

    public function test_usage_reports_how_much_of_each_limit_is_used(): void
    {
        $this->travelTo(now()->setTime(12, 0)); // 'today' must not depend on when the suite runs
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id, 'balance' => '9900', 'equity' => '9884.5']);
        $this->snapshot($account, 10000, '-1 day');
        $this->closedTrade($account, -100, '-10 minutes');
        $this->openTrade($account);
        $usage = collect($this->actingAs($this->viewer())->getJson("/api/risk/usage/{$account->id}")->assertOk()->json('usage'))->keyBy('key');
        $this->assertEqualsWithDelta(1.155, $usage['daily_loss']['used'], 0.006); // (100 + 15.5) / 10000
        $this->assertEquals(2.0, $usage['daily_loss']['limit']);
        $this->assertSame(1, $usage['open_positions']['used']);
        $this->assertSame(1, $usage['losing_streak']['used']);
        $this->assertEqualsWithDelta(1.16, $usage['drawdown']['used'], 0.01);
    }

    public function test_viewers_cannot_change_risk(): void
    {
        $this->actingAs($this->viewer())->postJson('/api/risk/profiles', $this->limits())->assertForbidden();
    }
}
