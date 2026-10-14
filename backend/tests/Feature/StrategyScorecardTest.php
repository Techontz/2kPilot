<?php

namespace Tests\Feature;

use App\Models\TradingAccount;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class StrategyScorecardTest extends TestCase
{
    use CreatesTradingData;

    /** Rise/Fall: $1 stake paying $1.79 → win +0.79, loss −1. */
    private function riseFall(TradingAccount $account, bool $won, string $symbol = 'frxEURUSD'): void
    {
        $this->closedTrade($account, $won ? 0.79 : -1.0, '-1 hour', [
            'symbol' => $symbol,
            'strategy_version_id' => $this->strategyVersion()->id,
            'contract_family' => 'RISE_FALL',
            'stake' => '1',
            'payout' => '1.79',
            'outcome' => $won ? 'WON' : 'LOST',
        ]);
    }

    public function test_a_few_trades_are_too_early_to_judge(): void
    {
        $account = $this->account();
        foreach ([true, false, true, false, false] as $won) {
            $this->riseFall($account, $won);
        }

        $row = $this->actingAs($this->me())->getJson("/api/analytics/scorecard?account_id={$account->id}")
            ->assertOk()->assertJsonPath('min_trades', 30)->json('rows.0');
        $this->assertSame('Trend Pullback V1', $row['strategy']);
        $this->assertSame(5, $row['trades']);
        $this->assertEquals(40, $row['win_rate']);
        $this->assertEquals(55.9, $row['break_even_win_rate']); // 1 / 1.79
        $this->assertSame('TOO_EARLY', $row['verdict']);
        $this->assertNull($row['confidence_z']);
    }

    public function test_coin_flip_results_on_rise_fall_have_no_edge(): void
    {
        $account = $this->account();
        for ($i = 0; $i < 40; $i++) {
            $this->riseFall($account, $i % 2 === 0); // 50% wins, below the 55.9% needed
        }

        $row = $this->actingAs($this->me())->getJson("/api/analytics/scorecard?account_id={$account->id}")->json('rows.0');
        $this->assertSame(40, $row['trades']);
        $this->assertEquals(50, $row['win_rate']);
        $this->assertLessThan(0, $row['net_pnl']);
        $this->assertSame('NO_EDGE', $row['verdict']); // losing a little, but within luck
    }

    public function test_steady_losses_and_steady_wins_get_clear_verdicts(): void
    {
        $account = $this->account();
        for ($i = 0; $i < 40; $i++) {
            $this->riseFall($account, $i % 5 === 0, 'R_75');      // 20% wins
            $this->riseFall($account, $i % 5 !== 0, 'frxGBPUSD'); // 80% wins
        }

        $rows = collect($this->actingAs($this->me())->getJson("/api/analytics/scorecard?account_id={$account->id}")->json('rows'))
            ->keyBy('symbol');
        $this->assertSame('LOSING', $rows['R_75']['verdict']);
        $this->assertSame('PROFITABLE', $rows['frxGBPUSD']['verdict']);
        $this->assertGreaterThan(2, $rows['frxGBPUSD']['confidence_z']);
        // Most profitable first.
        $this->assertSame('frxGBPUSD', $this->getJson("/api/analytics/scorecard?account_id={$account->id}")->json('rows.0.symbol'));
    }

    public function test_break_even_for_other_contracts_comes_from_average_win_and_loss(): void
    {
        $account = $this->account();
        $version = $this->strategyVersion()->id;
        foreach ([30, -10, -10] as $pnl) {
            $this->closedTrade($account, $pnl, '-1 hour', ['strategy_version_id' => $version, 'contract_family' => 'MULTIPLIER']);
        }

        $row = $this->actingAs($this->me())->getJson("/api/analytics/scorecard?account_id={$account->id}")->json('rows.0');
        $this->assertEquals(25, $row['break_even_win_rate']); // 10 / (30 + 10)
    }

    public function test_manual_trades_are_left_out_and_other_users_accounts_are_hidden(): void
    {
        $account = $this->account();
        $this->closedTrade($account, 50); // no strategy
        $this->actingAs($this->me())->getJson("/api/analytics/scorecard?account_id={$account->id}")
            ->assertOk()->assertJsonPath('rows', [])->assertJsonPath('simulated', true);

        $stranger = $this->user();
        $this->actingAs($stranger)->getJson("/api/analytics/scorecard?account_id={$account->id}")->assertNotFound();
        $this->getJson('/api/analytics/scorecard')->assertUnprocessable();
    }
}
