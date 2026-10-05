<?php

namespace Tests\Unit;

use App\Services\Analytics\Metrics;
use Carbon\CarbonImmutable;
use PHPUnit\Framework\TestCase;

class MetricsTest extends TestCase
{
    private function trade(float $pnl, int $day, ?float $r = null, string $symbol = 'EURUSD'): array
    {
        $exit = CarbonImmutable::parse('2026-09-01T12:00:00Z')->addDays($day);

        return ['net_pnl' => $pnl, 'entry_time' => $exit->subHours(4), 'exit_time' => $exit, 'symbol' => $symbol,
            'side' => 'BUY', 'session' => 'LONDON', 'strategy' => 'Trend Pullback V1', 'r_multiple' => $r, 'costs' => 1.0];
    }

    public function test_core_statistics(): void
    {
        $trades = [$this->trade(100, 0, 1.0), $this->trade(-50, 1, -0.5), $this->trade(200, 2, 2.0), $this->trade(-50, 3, -0.5)];
        $m = Metrics::compute($trades, 10000);
        $this->assertSame(200.0, $m['net_pnl']);
        $this->assertSame(2.0, $m['return_pct']);
        $this->assertSame(4, $m['trades']);
        $this->assertSame(50.0, $m['win_rate']);
        $this->assertSame(3.0, $m['profit_factor']); // 300 / 100
        $this->assertSame(50.0, $m['expectancy']);
        $this->assertSame(0.5, $m['expectancy_r']);
        $this->assertSame(3.0, $m['avg_rr']); // avg win 150 / avg loss 50
        $this->assertSame(50.0, $m['max_drawdown']); // 10100 → 10050
        $this->assertSame(0.5, $m['max_drawdown_pct']);
        $this->assertSame(4.0, $m['avg_holding_hours']);
        $this->assertSame(4.0, $m['total_costs']);
        $this->assertCount(5, $m['equity_curve']);
        $this->assertSame([['month' => '2026-09', 'net_pnl' => 200.0, 'trades' => 4, 'return_pct' => 2.0]], $m['monthly']);
    }

    public function test_no_losses_means_no_profit_factor_and_empty_is_safe(): void
    {
        $this->assertNull(Metrics::compute([$this->trade(10, 0)], 1000)['profit_factor']);
        $empty = Metrics::compute([], 1000);
        $this->assertSame(0, $empty['trades']);
        $this->assertNull($empty['win_rate']);
        $this->assertSame([], $empty['equity_curve']);
    }

    public function test_streaks_reset_on_breakeven(): void
    {
        $this->assertSame([2, 3], Metrics::streaks([true, true, null, false, false, false, true]));
    }

    public function test_grouping_and_periods(): void
    {
        $trades = [$this->trade(10, 0, symbol: 'EURUSD'), $this->trade(-5, 0, symbol: 'GBPUSD'), $this->trade(20, 8, symbol: 'EURUSD')];
        $groups = collect(Metrics::group($trades, 'symbol'))->keyBy('key');
        $this->assertSame(2, $groups['EURUSD']['trades']);
        $this->assertSame(100.0, $groups['EURUSD']['win_rate']);
        $this->assertNull($groups['EURUSD']['profit_factor']);
        $this->assertCount(2, Metrics::periodic($trades, 'Y-m-d'));
        $this->assertCount(2, Metrics::periodic($trades, 'o-\WW'));
    }

    public function test_downsample_keeps_the_last_point(): void
    {
        $points = range(1, 5000);
        $sample = Metrics::downsample($points, 100);
        $this->assertCount(100, $sample);
        $this->assertSame(5000, end($sample));
    }
}
