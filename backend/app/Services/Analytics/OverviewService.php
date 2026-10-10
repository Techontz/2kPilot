<?php

namespace App\Services\Analytics;

use App\Enums\AssignmentStatus;
use App\Enums\BacktestStatus;
use App\Enums\ContractFamily;
use App\Http\Controllers\Api\RecordsController;
use App\Models\AccountSnapshot;
use App\Models\AppNotification;
use App\Models\Backtest;
use App\Models\BrokerConnection;
use App\Models\RiskProfile;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Models\User;
use App\Services\Trading\Blockers;
use App\Services\Trading\TradingControl;
use App\Support\ContractSpec;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * The Overview page for ONE account: the numbers a trader needs, all taken
 * from stored broker data. Nothing is estimated or invented; a value the
 * broker never reported is returned as null and shown as "—".
 */
class OverviewService
{
    /** Days covered by `daily_pnl` and `balance_history`. */
    public const HISTORY_DAYS = 30;

    public function __construct(private readonly TradingControl $control, private readonly Blockers $blockers) {}

    /** The Overview when the user has no trading account yet. */
    public function withoutAccount(User $viewer): array
    {
        return [
            'account' => null,
            'robot' => $this->control->status($viewer)->toArray(),
            'setup' => $this->setup($viewer),
            'blockers' => [],
            'active_strategies' => [],
            'positions' => [],
            'daily_pnl' => [],
            'balance_history' => [],
        ];
    }

    public function forAccount(TradingAccount $account, User $viewer): array
    {
        $account->loadMissing('connection', 'riskProfile');
        $profile = $account->riskProfile;
        $todayStart = now()->startOfDay();
        $closed = Trade::query()->where('account_id', $account->id)->where('status', 'CLOSED')->whereNotNull('net_pnl');
        $open = Trade::query()->where('account_id', $account->id)->where('status', 'OPEN')
            ->with('account:id,label,environment,currency', 'version.strategy:id,name')->orderByDesc('entry_time')->get();

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
        $status = $this->control->status($viewer);
        $connection = $account->connection;
        $brokerName = config("brokers.{$connection->connector_type->value}.name");

        return [
            'account' => [
                'id' => $account->id,
                'label' => $account->label,
                'broker' => $brokerName,
                'connector_type' => $connection->connector_type->value,
                'environment' => $account->environment->value,
                'currency' => $account->currency,
                'balance' => $account->balance,
                'equity' => $account->equity,
                'broker_account_id' => $account->broker_account_id,
                'connection_id' => $account->connection_id,
                'connection_status' => $connection->status->value,
                'connection_detail' => $connection->status_detail,
                'last_connected_at' => $connection->last_connected_at?->toIso8601String(),
                'trading_enabled' => $account->trading_enabled,
                'synced_at' => $account->synced_at?->toIso8601String(),
                'risk_profile' => $profile?->name,
                'risk_profile_id' => $account->risk_profile_id,
            ],
            'broker' => [
                'name' => $brokerName,
                'connector_type' => $connection->connector_type->value,
                'connection_status' => $connection->status->value,
                'connection_detail' => $connection->status_detail,
                'last_connected_at' => $connection->last_connected_at?->toIso8601String(),
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
            'positions' => $open->map(fn (Trade $t) => RecordsController::present($t))->values(),
            'recent_trades' => (clone $closed)->with('account:id,label,environment,currency', 'version.strategy:id,name')
                ->orderByDesc('exit_time')->limit(6)->get()->map(fn (Trade $t) => RecordsController::present($t))->values(),
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
            'active_strategies' => $assignments->where('status', AssignmentStatus::Enabled)
                ->map(fn (StrategyAssignment $a) => $this->activeStrategy($a, $profile))->values(),
            'alerts' => $this->alerts($account, $drawdownPct, $dailyLossPct),
            'blockers' => $this->blockers->forAccount($viewer, $account, $status),
            'daily_pnl' => $this->dailyPnl($account),
            'balance_history' => $this->balanceHistory($account),
            'setup' => $this->setup($viewer),
        ];
    }

    /** What the user has set up so far (all their accounts, not only this one). */
    public function setup(User $user): array
    {
        $assignments = StrategyAssignment::query()->ownedBy($user);

        return [
            'has_broker' => BrokerConnection::query()->ownedBy($user)->exists(),
            'has_account' => TradingAccount::query()->ownedBy($user)->exists(),
            'has_strategy' => Strategy::query()->ownedBy($user)->active()->exists() || (clone $assignments)->exists(),
            'has_backtest' => Backtest::query()->ownedBy($user)->where('status', BacktestStatus::Completed)->exists(),
            'has_active_strategy' => (clone $assignments)->where('status', AssignmentStatus::Enabled)->exists(),
            'trading_started' => ! $this->control->stateOf($user)->kill_switch_engaged,
            'mfa_enabled' => $user->hasMfa(),
        ];
    }

    private function activeStrategy(StrategyAssignment $a, ?RiskProfile $profile): array
    {
        $contract = ContractSpec::fromAssignment($a);

        return [
            'assignment_id' => $a->id,
            'strategy_id' => $a->strategy_id,
            'strategy' => $a->strategy?->name,
            'version' => $a->version?->version,
            'symbol' => $a->symbol,
            'contract' => $contract,
            'contract_summary' => self::contractSummary($contract, $profile),
            'status_reason' => $a->status_reason,
            'last_bar_evaluated' => $a->last_bar_evaluated?->toIso8601String(),
            'last_signal_at' => $a->last_signal_at?->toIso8601String(),
        ];
    }

    /** The contract in plain words, e.g. "Rise/Fall · 5 minutes · stake 1.00". */
    public static function contractSummary(array $contract, ?RiskProfile $profile): string
    {
        $family = ContractFamily::tryFrom((string) ($contract['contract_family'] ?? '')) ?? ContractFamily::Spot;
        if ($family === ContractFamily::Spot) {
            return 'Spot (lots sized by risk)';
        }
        $stake = $contract['stake'] !== null
            ? 'stake '.number_format((float) $contract['stake'], 2, '.', '')
            : 'stake from risk profile'.($profile ? ' ('.number_format((float) $profile->stake_amount, 2, '.', '').')' : '');
        $parts = [$family->label()];
        if ($family === ContractFamily::RiseFall) {
            $units = ['t' => 'tick', 's' => 'second', 'm' => 'minute', 'h' => 'hour', 'd' => 'day'];
            $n = (int) $contract['duration'];
            $unit = $units[$contract['duration_unit']] ?? (string) $contract['duration_unit'];
            $parts[] = $n.' '.$unit.($n === 1 ? '' : 's');
        } else {
            $parts[0] .= ' ×'.$contract['multiplier'];
        }
        $parts[] = $stake;

        return implode(' · ', $parts);
    }

    /** @return list<array{date: string, net_pnl: float, trades: int}> realised P/L per UTC day, oldest first */
    private function dailyPnl(TradingAccount $account): array
    {
        $from = now()->utc()->startOfDay()->subDays(self::HISTORY_DAYS - 1);
        $rows = Trade::query()->where('account_id', $account->id)->where('status', 'CLOSED')->whereNotNull('net_pnl')
            ->where('exit_time', '>=', $from)
            ->groupBy(DB::raw('DATE(exit_time)'))
            ->get([DB::raw('DATE(exit_time) as day'), DB::raw('SUM(net_pnl) as pnl'), DB::raw('COUNT(*) as n')])
            ->keyBy(fn ($r) => substr((string) $r->day, 0, 10));
        $out = [];
        for ($i = 0; $i < self::HISTORY_DAYS; $i++) {
            $day = $from->copy()->addDays($i)->toDateString();
            $row = $rows->get($day);
            $out[] = ['date' => $day, 'net_pnl' => round((float) ($row->pnl ?? 0), 2), 'trades' => (int) ($row->n ?? 0)];
        }

        return $out;
    }

    /**
     * Balance and equity over the last 30 days: the last snapshot of each day,
     * or of each hour when the history covers two days or less.
     *
     * @return list<array{t: string, balance: float, equity: float}>
     */
    private function balanceHistory(TradingAccount $account): array
    {
        $base = AccountSnapshot::query()->where('account_id', $account->id)->where('taken_at', '>=', now()->subDays(self::HISTORY_DAYS));
        $first = (clone $base)->min('taken_at');
        if ($first === null) {
            return [];
        }
        $format = Carbon::parse($first)->gt(now()->subDays(2)) ? '%Y-%m-%d %H' : '%Y-%m-%d';
        $latest = (clone $base)->groupBy(DB::raw("DATE_FORMAT(taken_at, '{$format}')"))->select(DB::raw('MAX(taken_at)'));
        $points = (clone $base)->whereIn('taken_at', $latest)->orderBy('taken_at')->get(['taken_at', 'balance', 'equity'])
            ->unique(fn ($s) => $s->taken_at->format('Y-m-d H:i:s.u'))->values();
        if ($points->count() > 60) { // evenly thinned, keeping the newest point
            $step = $points->count() / 60;
            $points = collect(range(1, 60))->map(fn ($i) => $points[(int) ceil($i * $step) - 1]);
        }

        return $points->map(fn ($s) => ['t' => $s->taken_at->toIso8601String(), 'balance' => (float) $s->balance, 'equity' => (float) $s->equity])
            ->values()->all();
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
            ->where(fn ($q) => $q->where('account_id', $account->id)->orWhere(fn ($q2) => $q2->whereNull('account_id')->where('user_id', $account->user_id)))
            ->whereIn('type', ['risk.limit_reached', 'risk.rejected', 'reconciliation.mismatch', 'order.unknown', 'broker.error', 'system.engine_offline'])
            ->whereNull('read_at')->where('created_at', '>=', now()->subDay())
            ->orderByDesc('created_at')->limit(5)->get();
        foreach ($recent as $note) {
            $alerts[] = ['severity' => $note->severity, 'message' => $note->message, 'at' => $note->created_at?->toIso8601String()];
        }

        return $alerts;
    }
}
