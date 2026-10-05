<?php

namespace App\Services\Analytics;

use App\Models\AccountSnapshot;
use App\Models\Order;
use App\Models\Signal;
use App\Models\Trade;
use App\Models\TradingAccount;
use Carbon\CarbonImmutable;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;

/**
 * Analytics computed only from stored records — never invented.
 *
 * Scope is ONE account, or ONE environment group (PAPER, DEMO or LIVE).
 * Simulated (PAPER) results are never mixed with real broker results.
 */
class PerformanceService
{
    /** @return Collection<int, TradingAccount> */
    public function accountsFor(?string $accountId, ?string $environment): Collection
    {
        if ($accountId !== null) {
            return TradingAccount::query()->whereKey($accountId)->get();
        }

        return TradingAccount::query()->where('environment', $environment ?? 'PAPER')->get();
    }

    public function performance(?string $accountId, ?string $environment, ?CarbonImmutable $since): array
    {
        $accounts = $this->accountsFor($accountId, $environment);
        $ids = $accounts->pluck('id');
        $scope = $accountId !== null
            ? ['type' => 'account', 'label' => $accounts->first()?->label, 'environment' => $accounts->first()?->environment->value]
            : ['type' => 'environment', 'label' => ($environment ?? 'PAPER').' accounts', 'environment' => $environment ?? 'PAPER'];
        if ($ids->isEmpty()) {
            return ['has_data' => false, 'scope' => $scope, 'simulated' => $scope['environment'] === 'PAPER'];
        }

        $rows = Trade::query()
            ->leftJoin('strategy_versions', 'trades.strategy_version_id', '=', 'strategy_versions.id')
            ->leftJoin('strategies', 'strategy_versions.strategy_id', '=', 'strategies.id')
            ->whereIn('trades.account_id', $ids)
            ->where('trades.status', 'CLOSED')
            ->whereNotNull('trades.net_pnl')
            ->when($since, fn ($q) => $q->where('trades.exit_time', '>=', $since))
            ->orderBy('trades.exit_time')
            ->get(['trades.*', 'strategies.name as strategy_name']);
        $stats = $rows->map(fn (Trade $t) => [
            'net_pnl' => (float) $t->net_pnl,
            'entry_time' => $t->entry_time,
            'exit_time' => $t->exit_time ?? $t->entry_time,
            'symbol' => $t->symbol,
            'side' => $t->side,
            'session' => $t->session ?? '—',
            'strategy' => $t->strategy_name ?? ($t->signal_id ? 'Manual' : 'Manual / external'),
            'r_multiple' => $t->r_multiple !== null ? (float) $t->r_multiple : null,
            'costs' => -((float) $t->commission + (float) $t->swap),
        ])->all();

        $snapshots = AccountSnapshot::query()
            ->whereIn('account_id', $ids)
            ->when($since, fn ($q) => $q->where('taken_at', '>=', $since))
            ->orderBy('taken_at')
            ->get();
        // Sum the latest snapshot of each account at every timestamp.
        $latest = [];
        $equityPoints = [];
        $balanceHistory = [];
        foreach ($snapshots as $s) {
            $latest[$s->account_id] = [(float) $s->balance, (float) $s->equity];
            $equity = array_sum(array_column($latest, 1));
            $balance = array_sum(array_column($latest, 0));
            $equityPoints[] = [$s->taken_at, $equity];
            $balanceHistory[] = ['t' => $s->taken_at->toIso8601String(), 'balance' => round($balance, 2), 'equity' => round($equity, 2)];
        }
        $netClosed = array_sum(array_column($stats, 'net_pnl'));
        $starting = $equityPoints ? $equityPoints[0][1] : (float) $accounts->sum(fn ($a) => (float) $a->balance) - $netClosed;
        $report = Metrics::compute($stats, $starting > 0 ? $starting : 1.0, $equityPoints ?: null);

        $open = Trade::query()->whereIn('account_id', $ids)->where('status', 'OPEN')->get();
        $report['unrealized_pnl'] = round((float) $open->sum(fn ($t) => (float) $t->unrealized_pnl), 2);
        $report['open_positions'] = $open->count();
        $report['balance_history'] = Metrics::downsample($balanceHistory);
        $report['daily'] = Metrics::periodic($stats, 'Y-m-d');
        $report['weekly'] = Metrics::periodic($stats, 'o-\WW');
        $report['execution'] = $this->executionQuality($ids, $since);
        $report['has_data'] = $stats !== [] || $snapshots->isNotEmpty();
        $report['scope'] = $scope;
        $report['simulated'] = $accounts->every(fn ($a) => $a->isPaper());
        $report['accounts'] = $accounts->map(fn ($a) => ['id' => $a->id, 'label' => $a->label, 'environment' => $a->environment->value])->values();

        return $report;
    }

    public function executionQuality(Collection $ids, ?CarbonImmutable $since): array
    {
        $orders = Order::query()->whereIn('account_id', $ids)->where('purpose', 'ENTRY')
            ->when($since, fn ($q) => $q->where('created_at', '>=', $since))->get();
        $byStatus = $orders->countBy('status')->all();
        $trades = Trade::query()->whereIn('account_id', $ids)->whereNotNull('slippage_pips')
            ->when($since, fn ($q) => $q->where('entry_time', '>=', $since))->get();
        $slippage = $trades->pluck('slippage_pips')->map(fn ($v) => (float) $v);
        $latency = $orders->filter(fn ($o) => $o->filled_at && $o->submitted_at && $o->filled_at->gte($o->submitted_at))
            ->map(fn ($o) => $o->submitted_at->diffInMilliseconds($o->filled_at) / 1000);
        $signals = Signal::query()->whereIn('account_id', $ids)->select('status', DB::raw('count(*) as n'))
            ->groupBy('status')->pluck('n', 'status')->map(fn ($n) => (int) $n)->all();
        $rejections = Signal::query()->whereIn('account_id', $ids)->where('status', 'REJECTED')
            ->select('rejection_reason', DB::raw('count(*) as n'))->groupBy('rejection_reason')
            ->orderByDesc('n')->limit(8)->get()
            ->map(fn ($r) => ['reason' => $r->rejection_reason ?? '—', 'count' => (int) $r->n])->all();
        $filled = ($byStatus['FILLED'] ?? 0) + ($byStatus['PARTIALLY_FILLED'] ?? 0);

        return [
            'orders' => $orders->count(),
            'orders_by_status' => $byStatus,
            'fill_rate' => $orders->count() ? round($filled / $orders->count() * 100, 1) : null,
            'avg_slippage_pips' => $slippage->isNotEmpty() ? round($slippage->avg(), 2) : null,
            'worst_slippage_pips' => $slippage->isNotEmpty() ? round($slippage->max(), 2) : null,
            'avg_fill_seconds' => $latency->isNotEmpty() ? round($latency->avg(), 2) : null,
            'unresolved_orders' => ($byStatus['UNKNOWN'] ?? 0) + ($byStatus['SUBMITTED'] ?? 0) + ($byStatus['PENDING_SUBMIT'] ?? 0),
            'signals_by_status' => $signals,
            'top_rejections' => $rejections,
        ];
    }
}
