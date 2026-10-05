<?php

namespace App\Services\Analytics;

/**
 * Trading statistics from closed trades and an equity curve. Pure functions,
 * matching trading-engine/src/fxrobot/analytics/metrics.py (used by backtests):
 *
 *  win rate      = winning trades ÷ trades
 *  expectancy    = average net P/L per trade; expectancy_r = average R-multiple
 *  profit factor = gross profit ÷ gross loss (null when there are no losses)
 *  max drawdown  = largest peak-to-trough fall of the equity curve
 *  avg R:R       = average win ÷ |average loss|
 *
 * A "trade" here is an array with keys: net_pnl (float), entry_time and
 * exit_time (Carbon), symbol, side, session, strategy, r_multiple (?float), costs (float).
 */
final class Metrics
{
    public static function compute(array $trades, float $startingBalance, ?array $equityPoints = null): array
    {
        usort($trades, fn ($a, $b) => $a['exit_time'] <=> $b['exit_time']);
        $n = count($trades);
        $net = array_sum(array_column($trades, 'net_pnl'));
        $wins = array_values(array_filter($trades, fn ($t) => $t['net_pnl'] > 0));
        $losses = array_values(array_filter($trades, fn ($t) => $t['net_pnl'] < 0));
        $grossProfit = array_sum(array_column($wins, 'net_pnl'));
        $grossLoss = -array_sum(array_column($losses, 'net_pnl'));
        $avgWin = $wins ? $grossProfit / count($wins) : null;
        $avgLoss = $losses ? -$grossLoss / count($losses) : null;
        $rs = array_values(array_filter(array_column($trades, 'r_multiple'), fn ($r) => $r !== null));
        [$bestWin, $bestLoss] = self::streaks(array_map(fn ($t) => $t['net_pnl'] == 0 ? null : $t['net_pnl'] > 0, $trades));

        if ($equityPoints === null) {
            $running = $startingBalance;
            $equityPoints = $n ? [[$trades[0]['entry_time'], $startingBalance]] : [];
            foreach ($trades as $t) {
                $running += $t['net_pnl'];
                $equityPoints[] = [$t['exit_time'], $running];
            }
        }
        [$ddCurve, $ddAmount, $ddPct] = self::drawdown($equityPoints);
        $holding = array_map(fn ($t) => $t['entry_time']->diffInSeconds($t['exit_time'], true) / 3600, $trades);

        return [
            'starting_balance' => self::r($startingBalance),
            'ending_balance' => self::r($startingBalance + $net),
            'net_pnl' => self::r($net),
            'return_pct' => $startingBalance > 0 ? self::r($net / $startingBalance * 100) : null,
            'trades' => $n,
            'wins' => count($wins),
            'losses' => count($losses),
            'breakeven' => $n - count($wins) - count($losses),
            'win_rate' => $n ? self::r(count($wins) / $n * 100, 1) : null,
            'avg_win' => self::r($avgWin),
            'avg_loss' => self::r($avgLoss),
            'largest_win' => $wins ? self::r(max(array_column($wins, 'net_pnl'))) : null,
            'largest_loss' => $losses ? self::r(min(array_column($losses, 'net_pnl'))) : null,
            'expectancy' => $n ? self::r($net / $n) : null,
            'expectancy_r' => $rs ? self::r(array_sum($rs) / count($rs), 3) : null,
            'profit_factor' => $grossLoss > 0 ? self::r($grossProfit / $grossLoss) : null,
            'gross_profit' => self::r($grossProfit),
            'gross_loss' => self::r($grossLoss),
            'avg_rr' => ($avgWin && $avgLoss) ? self::r($avgWin / -$avgLoss) : null,
            'max_consecutive_wins' => $bestWin,
            'max_consecutive_losses' => $bestLoss,
            'max_drawdown' => self::r($ddAmount),
            'max_drawdown_pct' => self::r($ddPct),
            'total_costs' => self::r(array_sum(array_column($trades, 'costs'))),
            'avg_holding_hours' => $holding ? round(array_sum($holding) / count($holding), 1) : null,
            'equity_curve' => self::downsample(array_map(
                fn ($p) => ['t' => $p[0]->toIso8601String(), 'equity' => self::r($p[1])], $equityPoints)),
            'drawdown_curve' => self::downsample($ddCurve),
            'monthly' => self::monthly($trades, $startingBalance),
            'by_symbol' => self::group($trades, 'symbol'),
            'by_session' => self::group($trades, 'session'),
            'by_side' => self::group($trades, 'side'),
            'by_strategy' => self::group($trades, 'strategy'),
        ];
    }

    /** @return array{0: int, 1: int} longest win / loss streaks; a breakeven (null) ends a streak */
    public static function streaks(array $results): array
    {
        $bestWin = $bestLoss = $current = 0;
        $last = null;
        foreach ($results as $won) {
            if ($won === null) {
                [$current, $last] = [0, null];

                continue;
            }
            $current = $won === $last ? $current + 1 : 1;
            $last = $won;
            $won ? $bestWin = max($bestWin, $current) : $bestLoss = max($bestLoss, $current);
        }

        return [$bestWin, $bestLoss];
    }

    /** @return array{0: array, 1: float, 2: float} curve, max drawdown amount, max drawdown % */
    public static function drawdown(array $points): array
    {
        $peak = null;
        $maxAmount = 0.0;
        $maxPct = 0.0;
        $curve = [];
        foreach ($points as [$moment, $equity]) {
            $peak = ($peak === null || $equity > $peak) ? $equity : $peak;
            $amount = $peak - $equity;
            $pct = $peak > 0 ? $amount / $peak * 100 : 0.0;
            $maxAmount = max($maxAmount, $amount);
            $maxPct = max($maxPct, $pct);
            $curve[] = ['t' => $moment->toIso8601String(), 'dd' => self::r(-$pct, 3)];
        }

        return [$curve, $maxAmount, $maxPct];
    }

    public static function group(array $trades, string $key): array
    {
        $groups = [];
        foreach ($trades as $t) {
            $groups[(string) ($t[$key] ?? '—') ?: '—'][] = $t;
        }
        ksort($groups);
        $out = [];
        foreach ($groups as $name => $items) {
            $wins = array_filter($items, fn ($t) => $t['net_pnl'] > 0);
            $gp = array_sum(array_column($wins, 'net_pnl'));
            $gl = -array_sum(array_column(array_filter($items, fn ($t) => $t['net_pnl'] < 0), 'net_pnl'));
            $out[] = [
                'key' => (string) $name,
                'trades' => count($items),
                'wins' => count($wins),
                'win_rate' => self::r(count($wins) / count($items) * 100, 1),
                'net_pnl' => self::r(array_sum(array_column($items, 'net_pnl'))),
                'profit_factor' => $gl > 0 ? self::r($gp / $gl) : null,
            ];
        }

        return $out;
    }

    public static function monthly(array $trades, float $starting): array
    {
        $byMonth = [];
        foreach ($trades as $t) {
            $month = $t['exit_time']->format('Y-m');
            $byMonth[$month]['pnl'] = ($byMonth[$month]['pnl'] ?? 0) + $t['net_pnl'];
            $byMonth[$month]['n'] = ($byMonth[$month]['n'] ?? 0) + 1;
        }
        ksort($byMonth);
        $balance = $starting;
        $out = [];
        foreach ($byMonth as $month => $row) {
            $out[] = [
                'month' => $month,
                'net_pnl' => self::r($row['pnl']),
                'trades' => $row['n'],
                'return_pct' => $balance > 0 ? self::r($row['pnl'] / $balance * 100) : null,
            ];
            $balance += $row['pnl'];
        }

        return $out;
    }

    /** Net P/L per period (format e.g. 'Y-m-d' or 'o-\WW'), most recent 120 periods. */
    public static function periodic(array $trades, string $format): array
    {
        $buckets = [];
        foreach ($trades as $t) {
            $key = $t['exit_time']->format($format);
            $buckets[$key]['pnl'] = ($buckets[$key]['pnl'] ?? 0) + $t['net_pnl'];
            $buckets[$key]['n'] = ($buckets[$key]['n'] ?? 0) + 1;
        }
        ksort($buckets);
        $out = [];
        foreach ($buckets as $period => $row) {
            $out[] = ['period' => (string) $period, 'net_pnl' => self::r($row['pnl']), 'trades' => $row['n']];
        }

        return array_slice($out, -120);
    }

    public static function downsample(array $points, int $limit = 1500): array
    {
        $count = count($points);
        if ($count <= $limit) {
            return array_values($points);
        }
        $step = $count / $limit;
        $picked = [];
        for ($i = 0; $i < $limit; $i++) {
            $picked[] = $points[(int) ($i * $step)];
        }
        $picked[$limit - 1] = $points[$count - 1];

        return $picked;
    }

    private static function r(?float $value, int $places = 2): ?float
    {
        return $value === null ? null : round($value, $places);
    }
}
