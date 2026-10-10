<?php

namespace Tests\Feature;

use App\Enums\AccountEnvironment;
use App\Enums\ConnectorType;
use App\Models\AuditLog;
use App\Models\Backtest;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\UserTradingState;
use App\Services\Strategies\StrategyTemplates;
use Illuminate\Http\Client\Request as HttpRequest;
use Illuminate\Support\Facades\Http;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

/**
 * Rule-based strategies: templates, the builder (create / version / rename /
 * delete), import & export, plain-English drafts and one-click activation —
 * with the trading engine faked.
 */
class StrategyBuilderTest extends TestCase
{
    use CreatesTradingData;

    private const RULES = [
        'schema_version' => 1,
        'timeframe' => 'M5',
        'entry' => ['buy' => ['all' => [[
            'left' => ['indicator' => 'ema', 'params' => ['period' => 9]],
            'op' => 'crosses_above',
            'right' => ['indicator' => 'ema', 'params' => ['period' => 21]],
        ]]]],
    ];

    /** The engine's validate endpoint: echoes the rules back as the normalised parameters. */
    private function fakeValidator(array $more = []): void
    {
        Http::fake($more + [
            'engine.test/internal/strategies/rules/validate' => fn (HttpRequest $r) => Http::response([
                'parameters' => $r['parameters'],
                'code_version' => '1.0.0',
                'rules_text' => 'Buy when EMA 9 crosses above EMA 21.',
                'notes' => [],
            ]),
            'engine.test/internal/strategies' => Http::response([]),
        ]);
    }

    private function createStrategy(string $name = 'My EMA cross', array $rules = self::RULES): array
    {
        return $this->actingAs($this->me())->postJson('/api/strategies', ['name' => $name, 'description' => 'mine', 'rules' => $rules])
            ->assertCreated()->json();
    }

    public function test_templates_are_seeded_shared_and_read_only(): void
    {
        $this->fakeEngine(['/internal/strategies' => []]);
        $list = collect($this->actingAs($this->me())->getJson('/api/strategies')->assertOk()->json());
        $templates = $list->where('source', 'template')->where('key', 'rules');
        $this->assertEqualsCanonicalizing(
            ['ema-crossover', 'rsi-mean-reversion', 'ma-trend-filter', 'bollinger-reversion', 'macd-momentum', 'breakout'],
            $templates->pluck('slug')->all());
        $ema = $templates->firstWhere('slug', 'ema-crossover');
        $this->assertTrue($ema['built_in']);
        $this->assertFalse($ema['editable']);
        $this->assertStringStartsWith('Buy when EMA 9 crosses above EMA 21.', $ema['rules_text']);
        $this->assertSame('beginner', $ema['details']['difficulty']);
        $this->assertEquals(['contract_family' => 'RISE_FALL', 'duration' => 25, 'duration_unit' => 'm'], $ema['details']['suggested_contract']);
        $this->assertStringContainsString('Educational', $ema['details']['disclaimer']);
        $this->assertSame(1, $ema['latest_version']['version']);
        $this->assertSame(['demo' => ['trades' => 0, 'wins' => 0, 'win_rate' => null, 'net_pnl' => 0, 'net_pnl_30d' => 0, 'last_trade_at' => null], 'live' => null], $ema['performance']);
        $this->assertNull($ema['backtest']);

        $this->patchJson("/api/strategies/{$ema['id']}", ['name' => 'Mine now'])->assertForbidden();
        $this->deleteJson("/api/strategies/{$ema['id']}")->assertForbidden();
        $this->postJson("/api/strategies/{$ema['id']}/versions", ['rules' => self::RULES])->assertForbidden();
        $copy = $this->postJson("/api/strategies/{$ema['id']}/copy", ['name' => 'My EMA'])->assertCreated()->json();
        $this->assertSame('copy', $copy['source']);
        $this->assertSame($ema['id'], $copy['copied_from_id']);
        $this->assertSame($ema['rules_text'], $copy['versions'][0]['rules_text']);
    }

    public function test_templates_sync_is_idempotent(): void
    {
        $before = Strategy::query()->whereNull('user_id')->where('key', 'rules')->count();
        $this->assertSame(0, StrategyTemplates::sync());
        $this->assertSame($before, Strategy::query()->whereNull('user_id')->where('key', 'rules')->count());
    }

    public function test_catalog_comes_from_the_engine_and_is_cached(): void
    {
        $this->fakeEngine(['/internal/strategies/catalog' => ['schema_version' => 1, 'indicators' => [['key' => 'ema']], 'ai_drafting_available' => false]]);
        $this->actingAs($this->me())->getJson('/api/strategies/catalog')->assertOk()->assertJsonPath('ai_drafting_available', false)
            ->assertJsonPath('indicators.0.key', 'ema');
        $this->getJson('/api/strategies/catalog')->assertOk();
        Http::assertSentCount(1);
    }

    public function test_create_a_strategy_from_the_builder(): void
    {
        $this->fakeValidator();
        $created = $this->createStrategy();
        $this->assertSame('rules', $created['key']);
        $this->assertSame('builder', $created['source']);
        $this->assertFalse($created['built_in']);
        $this->assertSame(1, $created['latest_version']['version']);
        $this->assertSame('Buy when EMA 9 crosses above EMA 21.', $created['rules_text']);
        $this->assertEquals(self::RULES, $created['latest_version']['parameters']);
        $this->assertDatabaseHas('audit_logs', ['action' => 'strategy.created']);
        Http::assertSent(fn (HttpRequest $r) => str_ends_with($r->url(), '/internal/strategies/rules/validate'));

        // Names are unique per user — another user may reuse the name.
        $this->postJson('/api/strategies', ['name' => 'My EMA cross', 'rules' => self::RULES])->assertJsonValidationErrors('name');
        $this->actingAs($this->user())->postJson('/api/strategies', ['name' => 'My EMA cross', 'rules' => self::RULES])->assertCreated();
        $this->actingAs($this->me())->postJson('/api/strategies', ['name' => 'x', 'rules' => self::RULES, 'source' => 'template'])->assertJsonValidationErrors('source');
        $this->postJson('/api/strategies', ['name' => 'y'])->assertJsonValidationErrors('rules');

        // New versions accept `rules`; rename keeps the versions.
        $this->postJson("/api/strategies/{$created['id']}/versions", ['rules' => self::RULES, 'notes' => 'v2'])->assertCreated()
            ->assertJsonPath('version', 2)->assertJsonPath('rules_text', 'Buy when EMA 9 crosses above EMA 21.');
        $this->patchJson("/api/strategies/{$created['id']}", ['name' => 'Renamed', 'description' => null])->assertOk()
            ->assertJsonPath('name', 'Renamed')->assertJsonPath('description', '')->assertJsonCount(2, 'versions');
    }

    public function test_engine_validation_problems_reach_the_user(): void
    {
        $this->fakeEngine(['/internal/strategies/rules/validate' => Http::response(['error' => [
            'code' => 'invalid_strategy_config',
            'message' => 'This strategy has problems: Buy rule, condition 1: EMA 9 is compared with itself',
            'details' => ['problems' => ['Buy rule, condition 1: EMA 9 is compared with itself']],
        ]], 422)]);
        $this->actingAs($this->me())->postJson('/api/strategies', ['name' => 'Broken', 'rules' => self::RULES])
            ->assertStatus(422)->assertJsonPath('code', 'invalid_strategy_config')
            ->assertJsonPath('problems', ['Buy rule, condition 1: EMA 9 is compared with itself']);
        $this->assertDatabaseMissing('strategies', ['name' => 'Broken']);
    }

    public function test_others_strategies_cannot_be_changed_or_exported(): void
    {
        $this->fakeValidator();
        $mine = $this->createStrategy();
        $this->actingAs($this->user());
        $this->patchJson("/api/strategies/{$mine['id']}", ['name' => 'Hijack'])->assertForbidden();
        $this->deleteJson("/api/strategies/{$mine['id']}")->assertForbidden();
        $this->getJson("/api/strategies/{$mine['id']}/export")->assertForbidden();
        $this->postJson("/api/strategies/{$mine['id']}/versions", ['rules' => self::RULES])->assertForbidden();
        $this->postJson("/api/strategies/{$mine['id']}/copy", ['name' => 'Stolen'])->assertForbidden();
        $this->assertNotContains($mine['id'], collect($this->getJson('/api/strategies')->json())->pluck('id'));
    }

    public function test_export_import_round_trip(): void
    {
        $this->fakeValidator();
        $mine = $this->createStrategy();
        $file = $this->getJson("/api/strategies/{$mine['id']}/export")->assertOk()
            ->assertHeader('Content-Disposition', 'attachment; filename="my-ema-cross.tradepilot.json"')->json();
        $this->assertSame(['format', 'schema_version', 'name', 'description', 'rules'], array_keys($file));
        $this->assertSame('tradepilot.strategy', $file['format']);
        $this->assertEquals(self::RULES, $file['rules']);

        $this->postJson('/api/strategies/import', $file)->assertJsonValidationErrors('name'); // same name
        $imported = $this->postJson('/api/strategies/import', ['name' => 'Imported cross'] + $file)->assertCreated()->json();
        $this->assertSame('import', $imported['source']);
        $this->assertEquals(self::RULES, $imported['latest_version']['parameters']);

        $this->postJson('/api/strategies/import', ['format' => 'other'] + $file)->assertJsonValidationErrors('format');
        $this->postJson('/api/strategies/import', ['schema_version' => 2, 'name' => 'Future'] + $file)->assertJsonValidationErrors('schema_version');
        $huge = ['name' => 'Huge', 'rules' => self::RULES + ['padding' => str_repeat('x', 140_000)]] + $file;
        $this->postJson('/api/strategies/import', $huge)->assertJsonValidationErrors('rules');

        // Built-in templates can be exported too; code strategies cannot.
        $template = Strategy::query()->where('slug', 'breakout')->firstOrFail();
        $this->getJson("/api/strategies/{$template->id}/export")->assertOk()->assertJsonPath('rules.timeframe', 'M15');
        $pullback = $this->strategyVersion()->strategy;
        $this->getJson("/api/strategies/{$pullback->id}/export")->assertStatus(422)->assertJsonPath('code', 'not_exportable');
    }

    public function test_plain_english_draft_is_returned_not_saved_and_audited_without_the_text(): void
    {
        $this->fakeEngine(['/internal/strategies/draft' => [
            'rules' => self::RULES, 'rules_text' => 'Buy when EMA 9 crosses above EMA 21.', 'notes' => [],
            'explanation' => 'Buys on a fast/slow EMA cross.', 'warnings' => ['Test on demo first.'],
            'unsupported' => ['News trading'], 'model' => 'claude-opus-5-5',
        ]]);
        $description = 'Buy when the 9 EMA crosses the 21 EMA, and avoid the news';
        $before = Strategy::query()->count();
        $this->actingAs($this->me())->postJson('/api/strategies/draft', ['description' => $description, 'timeframe' => 'M5', 'contract_family' => 'RISE_FALL'])
            ->assertOk()->assertExactJson([
                'rules' => self::RULES, 'rules_text' => 'Buy when EMA 9 crosses above EMA 21.', 'explanation' => 'Buys on a fast/slow EMA cross.',
                'warnings' => ['Test on demo first.'], 'unsupported' => ['News trading'], 'notes' => [], 'model' => 'claude-opus-5-5',
            ]);
        $this->assertSame($before, Strategy::query()->count(), 'a draft is never saved');
        Http::assertSent(fn (HttpRequest $r) => str_ends_with($r->url(), '/internal/strategies/draft')
            && $r['description'] === $description && $r['contract_family'] === 'RISE_FALL' && ! isset($r['symbol']));
        $log = AuditLog::query()->where('action', 'strategy.ai_draft')->firstOrFail();
        $this->assertSame(mb_strlen($description), $log->details['description_length']);
        $this->assertSame('drafted', $log->details['outcome']);
        $this->assertStringNotContainsString('9 EMA', json_encode($log->details));

        $this->postJson('/api/strategies/draft', ['description' => 'short'])->assertJsonValidationErrors('description');
        $this->postJson('/api/strategies/draft', ['description' => str_repeat('a', 2001)])->assertJsonValidationErrors('description');
    }

    public function test_draft_when_ai_is_not_configured_and_throttling(): void
    {
        $this->fakeEngine(['/internal/strategies/draft' => Http::response(['error' => ['code' => 'ai_not_configured', 'message' => 'x']], 503)]);
        $this->actingAs($this->me());
        $this->postJson('/api/strategies/draft', ['description' => 'Buy when RSI is below 30'])->assertStatus(503)
            ->assertJsonPath('code', 'ai_not_configured')->assertJsonPath('message', "Plain-English drafting isn't set up on this server.");
        $this->assertDatabaseHas('audit_logs', ['action' => 'strategy.ai_draft', 'outcome' => 'failure']);
        for ($i = 0; $i < 9; $i++) {
            $this->postJson('/api/strategies/draft', ['description' => 'Buy when RSI is below 30'])->assertStatus(503);
        }
        $this->postJson('/api/strategies/draft', ['description' => 'Buy when RSI is below 30'])->assertStatus(429);
    }

    public function test_activate_and_deactivate(): void
    {
        $this->travelTo('2026-03-04 14:00:00'); // a Wednesday: the EURUSD market is open
        $template = Strategy::query()->where('slug', 'rsi-mean-reversion')->firstOrFail();
        $account = $this->account();
        $this->actingAs($this->me())->postJson("/api/strategies/{$template->id}/activate", ['account_id' => $account->id, 'symbol' => 'EURUSD'])
            ->assertForbidden()->assertJsonPath('code', 'risk_profile_required');

        $account->update(['risk_profile_id' => $this->defaultProfile()->id]);
        $res = $this->postJson("/api/strategies/{$template->id}/activate", ['account_id' => $account->id, 'symbol' => 'EURUSD'])->assertOk()
            ->assertJsonPath('status', 'ENABLED')->assertJsonPath('contract.contract_family', 'SPOT')->assertJsonPath('will_trade', false)->json();
        $codes = array_column($res['blockers'], 'code');
        $this->assertContains('trading_stopped', $codes); // new users start STOPPED
        $this->assertContains('account_trading_disabled', $codes);
        $this->assertStringStartsWith('Enabled — but nothing will trade until:', $res['status_reason']);

        // Activating again updates the same assignment (no duplicates).
        UserTradingState::query()->whereKey($this->me()->id)->update(['kill_switch_engaged' => false]);
        $account->update(['trading_enabled' => true]);
        $this->engineAlive();
        $this->postJson("/api/strategies/{$template->id}/activate", ['account_id' => $account->id, 'symbol' => 'EURUSD'])->assertOk()
            ->assertJsonPath('will_trade', true)->assertJsonPath('blockers', []);
        $this->assertSame(1, StrategyAssignment::query()->where('strategy_id', $template->id)->count());

        $this->postJson("/api/strategies/{$template->id}/deactivate", ['account_id' => $account->id])->assertOk()
            ->assertJsonPath('paused', 1)->assertJsonPath('assignments.0.status', 'PAUSED');

        // Someone else's account is never reachable.
        $other = $this->account(owner: $this->user());
        $this->postJson("/api/strategies/{$template->id}/activate", ['account_id' => $other->id, 'symbol' => 'EURUSD'])->assertNotFound();
    }

    public function test_activate_checks_the_contract_with_the_broker(): void
    {
        $this->fakeEngine(['/internal/accounts' => Http::response(['error' => ['code' => 'unsupported_contract', 'message' => 'A 25m Rise/Fall is not offered on R_75.']], 422)]);
        $template = Strategy::query()->where('slug', 'ema-crossover')->firstOrFail();
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id], ConnectorType::Deriv);
        $this->actingAs($this->me())->postJson("/api/strategies/{$template->id}/activate", [
            'account_id' => $account->id, 'symbol' => 'R_75',
            'contract' => ['contract_family' => 'RISE_FALL', 'duration' => 25, 'duration_unit' => 'm'],
        ])->assertJsonValidationErrors(['contract_family' => 'not offered']);
        $this->postJson("/api/strategies/{$template->id}/activate", [
            'account_id' => $account->id, 'symbol' => 'R_75', 'contract' => ['contract_family' => 'RISE_FALL'],
        ])->assertJsonValidationErrors('contract.duration');
        $this->assertSame(0, StrategyAssignment::query()->count());
    }

    public function test_performance_separates_demo_from_live_and_ignores_other_users(): void
    {
        $this->fakeValidator();
        $mine = $this->createStrategy();
        $versionId = $mine['latest_version']['id'];
        $paper = $this->account();
        $live = $this->account(['environment' => AccountEnvironment::Live], ConnectorType::Deriv);
        $this->closedTrade($paper, 30, '-1 hour', ['strategy_version_id' => $versionId]);
        $this->closedTrade($paper, -10, '-40 days', ['strategy_version_id' => $versionId]);
        $this->closedTrade($live, 500, '-2 hours', ['strategy_version_id' => $versionId]);
        $someoneElse = $this->account(owner: $this->user());
        $this->closedTrade($someoneElse, 999, '-1 hour', ['strategy_version_id' => $versionId]);
        Backtest::query()->forceCreate([
            'user_id' => $this->me()->id, 'kind' => 'SINGLE', 'status' => 'COMPLETED', 'strategy_key' => 'rules', 'strategy_version_id' => $versionId,
            'code_version' => '1.0.0', 'parameters' => self::RULES, 'symbol' => 'R_75', 'timeframe' => 'M5', 'data_source' => 'synthetic',
            'start' => now()->subMonth(), 'end' => now(), 'initial_capital' => 1000, 'account_currency' => 'USD', 'risk_settings' => [], 'costs' => [],
            'config' => ['contract' => ['contract_family' => 'RISE_FALL']], 'finished_at' => now(),
            'metrics' => ['net_pnl' => 12.5, 'win_rate' => 54.2, 'trades' => 48, 'max_drawdown' => 30.1, 'max_drawdown_pct' => 3.0, 'return_pct' => 1.25],
        ]);

        $item = collect($this->actingAs($this->me())->getJson('/api/strategies')->assertOk()->json())->firstWhere('id', $mine['id']);
        $this->assertSame(2, $item['performance']['demo']['trades']);
        $this->assertSame(50.0, (float) $item['performance']['demo']['win_rate']);
        $this->assertSame(20.0, (float) $item['performance']['demo']['net_pnl']);
        $this->assertSame(30.0, (float) $item['performance']['demo']['net_pnl_30d']);
        $this->assertNotNull($item['performance']['demo']['last_trade_at']);
        $this->assertSame(1, $item['performance']['live']['trades']);
        $this->assertSame(500.0, (float) $item['performance']['live']['net_pnl']);
        $this->assertSame(12.5, $item['backtest']['net_pnl']);
        $this->assertSame(48, $item['backtest']['trades']);
        $this->assertSame('RISE_FALL', $item['backtest']['contract_family']);
        $this->assertNotNull($item['backtest']['run_at']);
    }

    public function test_delete_archive_and_refuse_while_enabled(): void
    {
        $this->fakeValidator();
        $plain = $this->createStrategy('Throwaway');
        $this->deleteJson("/api/strategies/{$plain['id']}")->assertOk()->assertJsonPath('outcome', 'deleted');
        $this->assertDatabaseMissing('strategies', ['id' => $plain['id']]);

        $used = $this->createStrategy('Used');
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id]);
        $this->postJson("/api/strategies/{$used['id']}/activate", ['account_id' => $account->id, 'symbol' => 'EURUSD'])->assertOk();
        $this->deleteJson("/api/strategies/{$used['id']}")->assertStatus(409)->assertJsonPath('code', 'strategy_in_use');
        $this->postJson("/api/strategies/{$used['id']}/deactivate", ['account_id' => $account->id])->assertOk();
        $this->closedTrade($account, 5, '-1 hour', ['strategy_version_id' => $used['latest_version']['id']]);
        $this->deleteJson("/api/strategies/{$used['id']}")->assertOk()->assertJsonPath('outcome', 'archived');
        $this->assertNotContains($used['id'], collect($this->getJson('/api/strategies')->json())->pluck('id'));
        $this->assertContains($used['id'], collect($this->getJson('/api/strategies?archived=1')->json())->pluck('id'));
        $this->createStrategy('Used'); // the name is free again
        $this->postJson("/api/strategies/{$used['id']}/versions", ['rules' => self::RULES])->assertStatus(409);
        $this->postJson("/api/strategies/{$used['id']}/activate", ['account_id' => $account->id, 'symbol' => 'EURUSD'])->assertStatus(409);
    }
}
