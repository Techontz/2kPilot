<?php

namespace Tests\Feature;

use App\Enums\ConnectorType;
use App\Models\AppNotification;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\StrategyVersion;
use Illuminate\Support\Facades\Schema;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

/**
 * Adaptive Trend & Momentum (registered by the engine), the strategy emergency
 * stop (admins), contract/market support checks and the minimum-balance limit.
 */
class AdaptiveStrategyTest extends TestCase
{
    use CreatesTradingData;

    private const CATALOG = [[
        'key' => 'adaptive_trend_momentum', 'name' => 'Adaptive Trend & Momentum', 'code_version' => '1.0.0',
        'description' => 'Uses trend, momentum, and volatility filters to identify potential trading opportunities while controlling risk.',
        'parameter_schema' => ['properties' => ['min_adx' => ['type' => 'number', 'default' => 25]]],
        'defaults' => ['min_adx' => 25], 'contract_families' => ['SPOT', 'MULTIPLIER'], 'symbols' => ['R_10', 'R_25'],
    ]];

    /** The built-in as the engine registers it on start-up. */
    private function adaptive(): Strategy
    {
        $strategy = Strategy::query()->create([
            'key' => 'adaptive_trend_momentum', 'name' => 'Adaptive Trend & Momentum', 'slug' => 'adaptive-trend-momentum',
            'description' => self::CATALOG[0]['description'], 'source' => 'template', 'summary' => '',
            'details' => ['supported_contract_families' => ['SPOT', 'MULTIPLIER'], 'supported_symbols' => ['R_10', 'R_25'], 'difficulty' => 'advanced'],
        ]);
        StrategyVersion::query()->create(['strategy_id' => $strategy->id, 'version' => 1, 'code_version' => '1.0.0', 'parameters' => ['min_adx' => 25], 'notes' => 'defaults']);

        return $strategy;
    }

    public function test_migration_adds_the_new_columns(): void
    {
        $this->assertTrue(Schema::hasColumns('strategies', ['entries_disabled_at', 'entries_disabled_reason', 'entries_disabled_by']));
        $this->assertTrue(Schema::hasColumn('risk_profiles', 'min_account_balance'));
        $this->assertTrue(Schema::hasColumn('backtest_trades', 'regime'));
    }

    public function test_admin_emergency_stop_blocks_entries_is_audited_and_notifies_users(): void
    {
        $this->fakeEngine(['/internal/strategies' => self::CATALOG]);
        $strategy = $this->adaptive();
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id]);
        StrategyAssignment::query()->create(['strategy_id' => $strategy->id, 'strategy_version_id' => $strategy->versions()->first()->id,
            'account_id' => $account->id, 'symbol' => 'R_10', 'status' => 'ENABLED']);
        $admin = $this->admin();

        $this->actingAs($this->me())->postJson("/api/admin/strategies/{$strategy->id}/disable", ['reason' => 'nope'])->assertForbidden();
        $this->actingAs($admin)->postJson("/api/admin/strategies/{$strategy->id}/disable", [])->assertJsonValidationErrors('reason');
        $this->postJson("/api/admin/strategies/{$strategy->id}/disable", ['reason' => 'Data feed under review'])->assertOk()
            ->assertJsonPath('entries_disabled', true)->assertJsonPath('entries_disabled_reason', 'Data feed under review');
        $strategy->refresh();
        $this->assertNotNull($strategy->entries_disabled_at);
        $this->assertSame($admin->id, $strategy->entries_disabled_by);
        $this->assertDatabaseHas('audit_logs', ['action' => 'strategy.entries_disabled', 'target_id' => $strategy->id]);
        $this->assertSame(1, AppNotification::query()->where('user_id', $this->me()->id)->where('type', 'strategy.entries_disabled')->count());
        // The assignment is left alone: positions and settings are never touched by the stop.
        $this->assertSame('ENABLED', StrategyAssignment::query()->firstOrFail()->status->value);

        // Users see it on the strategy (and on their copies of it).
        $copy = Strategy::query()->create(['user_id' => $this->me()->id, 'key' => 'adaptive_trend_momentum', 'name' => 'Mine',
            'description' => '', 'source' => 'copy', 'copied_from_id' => $strategy->id]);
        $list = collect($this->actingAs($this->me())->getJson('/api/strategies')->assertOk()->json());
        $this->assertSame('Data feed under review', $list->firstWhere('id', $strategy->id)['entries_disabled']['reason']);
        $this->assertTrue($list->firstWhere('id', $copy->id)['entries_disabled']['inherited']);
        $this->assertSame(['SPOT', 'MULTIPLIER'], $list->firstWhere('id', $strategy->id)['contract_families']);

        $this->actingAs($admin)->postJson("/api/admin/strategies/{$strategy->id}/enable", [])->assertJsonValidationErrors('confirm');
        $this->postJson("/api/admin/strategies/{$strategy->id}/enable", ['confirm' => true])->assertOk()->assertJsonPath('entries_disabled', false);
        $this->assertNull($strategy->refresh()->entries_disabled_at);
        $this->assertDatabaseHas('audit_logs', ['action' => 'strategy.entries_enabled', 'target_id' => $strategy->id]);
    }

    public function test_rise_fall_is_refused_for_the_strategy_with_a_clear_reason(): void
    {
        $this->fakeEngine(['/internal/strategies' => self::CATALOG, '/internal/accounts' => ['ok' => true]]);
        $strategy = $this->adaptive();
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id], ConnectorType::Deriv);
        $this->actingAs($this->me());

        // Omitted contract on Deriv would default to Rise/Fall: refused, never swapped silently.
        $this->postJson("/api/strategies/{$strategy->id}/activate", ['account_id' => $account->id, 'symbol' => 'R_10'])
            ->assertStatus(422)->assertJsonValidationErrors('contract_family');
        $res = $this->postJson("/api/strategies/{$strategy->id}/activate", ['account_id' => $account->id, 'symbol' => 'R_10',
            'contract' => ['contract_family' => 'RISE_FALL', 'duration' => 15, 'duration_unit' => 'm']])->assertStatus(422);
        $this->assertStringContainsString('Rise/Fall contracts have neither', $res->json('errors.contract_family.0'));
        $this->postJson('/api/assignments', ['strategy_version_id' => $strategy->versions()->first()->id, 'account_id' => $account->id,
            'symbol' => 'R_10', 'contract_family' => 'RISE_FALL', 'duration' => 15, 'duration_unit' => 'm'])->assertJsonValidationErrors('contract_family');
        $this->assertSame(0, StrategyAssignment::query()->count());

        // Unchecked markets are refused too.
        $this->postJson("/api/strategies/{$strategy->id}/activate", ['account_id' => $account->id, 'symbol' => 'R_100',
            'contract' => ['contract_family' => 'MULTIPLIER', 'multiplier' => 100]])->assertJsonValidationErrors('symbol');

        // Multipliers on R_10 are accepted.
        $this->postJson("/api/strategies/{$strategy->id}/activate", ['account_id' => $account->id, 'symbol' => 'R_10',
            'contract' => ['contract_family' => 'MULTIPLIER', 'multiplier' => 400]])->assertOk()
            ->assertJsonPath('contract.contract_family', 'MULTIPLIER')->assertJsonPath('status', 'ENABLED');

        // Switching an existing assignment to Rise/Fall is refused as well.
        $assignment = StrategyAssignment::query()->firstOrFail();
        $this->putJson("/api/assignments/{$assignment->id}/contract", ['contract_family' => 'RISE_FALL', 'duration' => 5, 'duration_unit' => 'm'])
            ->assertJsonValidationErrors('contract_family');
    }

    public function test_support_check_does_not_need_the_engine(): void
    {
        $this->engineDown();
        $strategy = $this->adaptive();
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id]);
        $this->actingAs($this->me())->postJson("/api/strategies/{$strategy->id}/activate", ['account_id' => $account->id, 'symbol' => 'R_10',
            'contract' => ['contract_family' => 'RISE_FALL', 'duration' => 15, 'duration_unit' => 'm']])->assertJsonValidationErrors('contract_family');
    }

    public function test_other_strategies_are_not_restricted(): void
    {
        $this->travelTo('2026-03-04 14:00:00');
        $template = Strategy::query()->where('slug', 'ema-crossover')->firstOrFail();
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id]);
        $this->fakeEngine(['/internal/strategies' => []]);
        $this->actingAs($this->me())->postJson("/api/strategies/{$template->id}/activate", ['account_id' => $account->id, 'symbol' => 'EURUSD'])->assertOk();
    }

    public function test_minimum_account_balance_is_an_optional_risk_limit(): void
    {
        $profile = $this->defaultProfile();
        $this->assertNull($profile->min_account_balance);
        $body = ['name' => 'Floor', 'risk_per_trade_pct' => 0.5, 'allowed_sessions' => ['LONDON'], 'max_data_age_seconds' => 120, 'stake_amount' => 1];
        $this->actingAs($this->me())->postJson('/api/risk/profiles', $body + ['min_account_balance' => -5])->assertJsonValidationErrors('min_account_balance');
        $created = $this->postJson('/api/risk/profiles', $body + ['min_account_balance' => 250])->assertCreated()->json();
        $this->assertSame('250.00', $created['min_account_balance']);
        $this->putJson("/api/risk/profiles/{$created['id']}", $body + ['min_account_balance' => null])->assertOk()->assertJsonPath('min_account_balance', null);
    }
}
