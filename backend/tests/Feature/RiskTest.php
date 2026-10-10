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
            'min_stop_pips' => 8, 'max_stop_pips' => 150, 'stake_amount' => 1,
        ], $overrides);
    }

    public function test_every_user_gets_their_own_beginner_profile(): void
    {
        $this->user(); // someone else's profile is never listed
        $this->actingAs($this->me())->getJson('/api/risk/profiles')->assertOk()->assertJsonCount(1)
            ->assertJsonPath('0.name', 'Beginner')->assertJsonPath('0.risk_per_trade_pct', '0.500');
    }

    public function test_profile_names_are_unique_per_user_only(): void
    {
        $this->actingAs($this->user())->postJson('/api/risk/profiles', $this->limits())->assertCreated();
        $this->actingAs($this->me())->postJson('/api/risk/profiles', $this->limits())->assertCreated();
        $this->postJson('/api/risk/profiles', $this->limits())->assertJsonValidationErrors('name');
    }

    public function test_profiles_are_validated_like_the_engine_does(): void
    {
        $owner = $this->me();
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
        $owner = $this->me();
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
        $usage = collect($this->actingAs($this->me())->getJson("/api/risk/usage/{$account->id}")->assertOk()->json('usage'))->keyBy('key');
        $this->assertEqualsWithDelta(1.155, $usage['daily_loss']['used'], 0.006); // (100 + 15.5) / 10000
        $this->assertEquals(2.0, $usage['daily_loss']['limit']);
        $this->assertSame(1, $usage['open_positions']['used']);
        $this->assertSame(1, $usage['losing_streak']['used']);
        $this->assertEqualsWithDelta(1.16, $usage['drawdown']['used'], 0.01);
    }

    public function test_beginner_profiles_include_conservative_contract_limits(): void
    {
        $profile = $this->defaultProfile();
        $this->assertSame('1.00', $profile->stake_amount);
        $this->assertSame('5.00', $profile->max_stake_amount);
        $this->assertSame(3, $profile->max_consecutive_losses);
        $this->assertNull($profile->max_daily_loss_amount);
        $this->assertNull($profile->daily_profit_target_amount);
        $this->assertSame(20, (int) $profile->max_trades_per_day);
    }

    public function test_contract_stake_limits_are_validated(): void
    {
        $this->actingAs($this->me())->postJson('/api/risk/profiles', $this->limits(['stake_amount' => null]))->assertJsonValidationErrors('stake_amount');
        $this->postJson('/api/risk/profiles', $this->limits(['stake_amount' => 0]))->assertJsonValidationErrors('stake_amount');
        $this->postJson('/api/risk/profiles', $this->limits(['stake_amount' => 10, 'max_stake_amount' => 5]))->assertStatus(422)
            ->assertJsonPath('errors.stake_amount.0', 'The stake per trade cannot be larger than the maximum stake.');
        $this->postJson('/api/risk/profiles', $this->limits(['max_daily_loss_amount' => -1, 'max_consecutive_losses' => 0, 'daily_profit_target_amount' => 0]))
            ->assertJsonValidationErrors(['max_daily_loss_amount', 'max_consecutive_losses', 'daily_profit_target_amount']);
        $this->postJson('/api/risk/profiles', $this->limits([
            'stake_amount' => 2.5, 'max_stake_amount' => 10, 'max_daily_loss_amount' => 25, 'max_consecutive_losses' => 4, 'daily_profit_target_amount' => 40,
        ]))->assertCreated()->assertJsonPath('stake_amount', '2.50')->assertJsonPath('max_stake_amount', '10.00')
            ->assertJsonPath('max_daily_loss_amount', '25.00')->assertJsonPath('max_consecutive_losses', 4)->assertJsonPath('daily_profit_target_amount', '40.00');
    }

    public function test_usage_reports_the_contract_limits(): void
    {
        $this->travelTo(now()->setTime(12, 0));
        $profile = $this->defaultProfile();
        $profile->update(['max_daily_loss_amount' => '10', 'daily_profit_target_amount' => '20']);
        $account = $this->account(['risk_profile_id' => $profile->id]);
        $this->closedTrade($account, -1, '-2 days'); // yesterday's loss does not count today
        $this->closedTrade($account, 1.95, '-3 hours');
        $this->closedTrade($account, -1, '-2 hours');
        $this->closedTrade($account, -1, '-1 hour');
        $usage = collect($this->actingAs($this->me())->getJson("/api/risk/usage/{$account->id}")->assertOk()->json('usage'))->keyBy('key');
        $this->assertEquals(0.05, $usage['daily_loss_amount']['used']); // net: 1.95 - 2
        $this->assertEquals(10.0, $usage['daily_loss_amount']['limit']);
        $this->assertSame('USD', $usage['daily_loss_amount']['unit']);
        $this->assertSame(2, $usage['losses_in_a_row_today']['used']);
        $this->assertEquals(3.0, $usage['losses_in_a_row_today']['limit']);
        $this->assertEquals(-0.05, $usage['profit_today']['used']);
        $this->assertEquals(20.0, $usage['profit_today']['limit']);
    }
}
