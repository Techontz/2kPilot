<?php

namespace Tests\Feature;

use App\Enums\AccountEnvironment;
use App\Enums\ConnectorType;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class AnalyticsAndOverviewTest extends TestCase
{
    use CreatesTradingData;

    public function test_paper_and_real_results_are_never_mixed(): void
    {
        $paper = $this->account(['label' => 'Paper']);
        $demo = $this->account(['label' => 'Deriv demo'], ConnectorType::Deriv);
        $this->closedTrade($paper, 100);
        $this->closedTrade($demo, -40);
        $viewer = $this->me();

        $paperReport = $this->actingAs($viewer)->getJson('/api/analytics/performance?environment=PAPER')->assertOk();
        $paperReport->assertJsonPath('net_pnl', 100)->assertJsonPath('trades', 1)->assertJsonPath('simulated', true)
            ->assertJsonPath('scope.environment', 'PAPER');
        $demoReport = $this->getJson('/api/analytics/performance?environment=DEMO')->assertOk();
        $demoReport->assertJsonPath('net_pnl', -40)->assertJsonPath('simulated', false);
        $this->getJson("/api/analytics/performance?account_id={$demo->id}")->assertJsonPath('scope.label', 'Deriv demo')->assertJsonPath('trades', 1);
    }

    public function test_analytics_without_data_is_an_empty_state(): void
    {
        $this->actingAs($this->me())->getJson('/api/analytics/performance?environment=LIVE')
            ->assertOk()->assertJsonPath('has_data', false);
    }

    public function test_overview_uses_only_stored_broker_figures(): void
    {
        $this->travelTo(now()->setTime(12, 0)); // 'today' must not depend on when the suite runs
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id, 'balance' => '10050', 'equity' => '10034.5']);
        $this->snapshot($account, 10100, '-2 days');
        $this->closedTrade($account, 50, '-1 hour');
        $this->closedTrade($account, -10, '-3 days');
        $this->openTrade($account);
        $body = $this->actingAs($this->me())->getJson("/api/overview?account_id={$account->id}")->assertOk()->json();
        $this->assertSame('PAPER', $body['account']['environment']);
        $this->assertSame('Paper Trading', $body['account']['broker']);
        $this->assertEquals(50, $body['figures']['today_pnl']);
        $this->assertEquals(40, $body['figures']['total_pnl']);
        $this->assertEquals(-15.5, $body['figures']['open_pnl']);
        $this->assertSame(1, $body['figures']['open_positions']);
        $this->assertEqualsWithDelta(0.65, $body['figures']['drawdown_pct'], 0.01); // (10100 - 10034.5) / 10100
        $this->assertEqualsWithDelta(0.40, $body['figures']['risk_used_pct'], 0.01); // 40 / 10034.5
        $this->assertSame('offline', $body['robot']['engine_state']);
        $this->assertCount(1, $body['positions']);
        $this->assertCount(2, $body['recent_trades']);
    }

    public function test_overview_without_accounts_and_missing_profile_alert(): void
    {
        $owner = $this->me();
        $this->actingAs($owner)->getJson('/api/overview')->assertOk()->assertJsonPath('account', null);
        $account = $this->account(['environment' => AccountEnvironment::Paper]);
        $alerts = $this->getJson('/api/overview')->json('alerts');
        $this->assertStringContainsString('No risk profile', $alerts[0]['message']);
        $this->assertNull($account->risk_profile_id);
    }
}
