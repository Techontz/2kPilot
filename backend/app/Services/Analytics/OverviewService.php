<?php

namespace App\Services\Analytics;

use App\Enums\AssignmentStatus;
use App\Models\AccountSnapshot;
use App\Models\AppNotification;
use App\Models\StrategyAssignment;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Services\Trading\TradingControl;

/**
 * The Overview page for ONE account: the numbers a trader needs, all taken
 * from stored broker data. Nothing is estimated or invented; a value the
 * broker never reported is returned as null and shown as "—".
 */
class OverviewService
{
    public function __construct(private readonly TradingControl $control) {}

    public function forAccount(TradingAccount $account): array
    {
        $account->loadMissing('connection', 'riskProfile');
        $profile = $account->riskProfile;
        $todayStart = now()->startOfDay();
        $closed = Trade::query()->where('account_id', $account->id)->where('status', 'CLOSED')->whereNotNull('net_pnl');
        $open = Trade::query()->where('account_id', $account->id)->where('status', 'OPEN')->orderByDesc('entry_time')->get();

        $equity = $account->equity !== null ? (float) $account->equity : null;
        $balance = $account->balance !== null ? (float) $account->balance : null;
        $todayPnl = (float) (clone $closed)->where('exit_time', '>=', $todayStart)->sum('net_pnl');
        $totalPnl = (float) (clone $closed)->sum('net_pnl');
        $openPnl = (float) $open->sum(fn ($t) => (float) $t->unrealized_pnl);
        $peak = (float) AccountSnapshot::query()->where('account_id', $account->id)->max('equity');
        $peak = max($peak, $equity ?? 0);
        $drawdownPct = ($equity !== null && $peak > 0) ? round(max(0, ($peak - $equity) / $peak * 100), 2) : null;
        $openRisk = (float) $open->sum(fn ($t) => (float) $t->risk_amount);
        $riskUsedPct = ($equity && $equity > 0) ? round($openRisk / $equity * 100, 2) : null;
        $startOfDayBalance = $balance !== null ? $balance - $todayPnl : null;
        $dailyLossPct = ($startOfDayBalance && $startOfDayBalance > 0)
            ? round(max(0, -($todayPnl + $openPnl)) / $startOfDayBalance * 100, 2) : null;

        $assignments = StrategyAssignment::query()->with('strategy', 'version')->where('account_id', $account->id)->get();
        $status = $this->control->status();

        return [
            'account' => [
                'id' => $account->id,
                'label' => $account->label,
                'broker' => config("brokers.{$account->connection->connector_type->value}.name"),
                'connector_type' => $account->connection->connector_type->value,
                'environment' => $account->environment->value,
                'currency' => $account->currency,
                'connection_status' => $account->connection->status->value,
                'connection_detail' => $account->connection->status_detail,
                'trading_enabled' => $account->trading_enabled,
                'synced_at' => $account->synced_at?->toIso8601String(),
                'risk_profile' => $profile?->name,
            ],
            'figures' => [
                'balance' => $balance,
                'equity' => $equity,
                'today_pnl' => round($todayPnl, 2),
                'total_pnl' => round($totalPnl, 2),
                'open_pnl' => round($openPnl, 2),
                'open_positions' => $open->count(),
                'drawdown_pct' => $drawdownPct,
                'max_drawdown_pct' => $profile?->max_drawdown_pct !== null ? (float) $profile->max_drawdown_pct : null,
                'risk_used_pct' => $riskUsedPct,
                'max_total_risk_pct' => $profile?->max_total_risk_pct !== null ? (float) $profile->max_total_risk_pct : null,
                'daily_loss_pct' => $dailyLossPct,
                'max_daily_loss_pct' => $profile?->max_daily_loss_pct !== null ? (float) $profile->max_daily_loss_pct : null,
                'active_strategies' => $assignments->where('status', AssignmentStatus::Enabled)->count(),
            ],
            'robot' => $status->toArray(),
            'equity_curve' => AccountSnapshot::query()->where('account_id', $account->id)
                ->orderByDesc('taken_at')->limit(500)->get(['taken_at', 'balance', 'equity'])->reverse()->values()
                ->map(fn ($s) => ['t' => $s->taken_at->toIso8601String(), 'balance' => (float) $s->balance, 'equity' => (float) $s->equity]),
            'positions' => $open->take(8)->values(),
            'recent_trades' => (clone $closed)->orderByDesc('exit_time')->limit(6)->get(),
            'strategies' => $assignments->map(fn ($a) => [
                'id' => $a->id,
                'strategy' => $a->strategy?->name,
                'version' => $a->version?->version,
                'symbol' => $a->symbol,
                'status' => $a->status->value,
                'status_reason' => $a->status_reason,
                'last_bar_evaluated' => $a->last_bar_evaluated?->toIso8601String(),
                'last_signal_at' => $a->last_signal_at?->toIso8601String(),
            ])->values(),
            'alerts' => $this->alerts($account, $drawdownPct, $dailyLossPct),
        ];
    }

    private function alerts(TradingAccount $account, ?float $drawdownPct, ?float $dailyLossPct): array
    {
        $alerts = [];
        $profile = $account->riskProfile;
        if ($profile === null) {
            $alerts[] = ['severity' => 'warning', 'message' => 'No risk profile assigned — this account cannot trade.'];
        }
        if ($profile?->max_daily_loss_pct && $dailyLossPct !== null && $dailyLossPct >= 0.8 * (float) $profile->max_daily_loss_pct) {
            $alerts[] = ['severity' => 'critical', 'message' => "Daily loss {$dailyLossPct}% is close to the {$profile->max_daily_loss_pct}% limit."];
        }
        if ($profile?->max_drawdown_pct && $drawdownPct !== null && $drawdownPct >= 0.8 * (float) $profile->max_drawdown_pct) {
            $alerts[] = ['severity' => 'critical', 'message' => "Drawdown {$drawdownPct}% is close to the {$profile->max_drawdown_pct}% limit."];
        }
        $recent = AppNotification::query()
            ->where(fn ($q) => $q->where('account_id', $account->id)->orWhereNull('account_id'))
            ->whereIn('type', ['risk.limit_reached', 'risk.rejected', 'reconciliation.mismatch', 'order.unknown', 'broker.error', 'system.engine_offline'])
            ->whereNull('read_at')->where('created_at', '>=', now()->subDay())
            ->orderByDesc('created_at')->limit(5)->get();
        foreach ($recent as $note) {
            $alerts[] = ['severity' => $note->severity, 'message' => $note->message, 'at' => $note->created_at?->toIso8601String()];
        }

        return $alerts;
    }
}
