<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Order;
use App\Models\Signal;
use App\Models\StrategyEvaluation;
use App\Models\StrategyVersion;
use App\Models\Trade;
use App\Models\TradeEvent;
use App\Services\Audit\AuditLogger;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Symfony\Component\HttpFoundation\StreamedResponse;

/** Orders, trade history, the journal and signals — read-only views of stored records. */
class RecordsController extends Controller
{
    /** The CSV export's columns, in order. */
    public const EXPORT_COLUMNS = ['opened_at', 'closed_at', 'account', 'environment', 'symbol', 'strategy', 'contract_type', 'direction',
        'stake/volume', 'entry', 'exit', 'fees', 'payout', 'net_pnl', 'outcome', 'duration_seconds'];

    public function __construct(private readonly AuditLogger $audit) {}

    public function orders(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $orders = Order::query()->ownedBy($request->user())->with('account:id,label,environment')
            ->when($request->query('account_id'), fn ($q, $id) => $q->where('account_id', $id))
            ->when($request->query('status'), fn ($q, $s) => $q->where('status', $s))
            ->orderByDesc('created_at')->paginate(min(100, (int) $request->query('per_page', 50)));

        return response()->json($orders);
    }

    public function history(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $filters = $request->validate(self::historyFilters());
        $trades = $this->closedTrades($request, $filters)
            ->orderByDesc('exit_time')->paginate(min(100, (int) $request->query('per_page', 50)));
        $trades->getCollection()->transform(fn (Trade $t) => self::present($t));

        return response()->json($trades);
    }

    /** Closed trades as CSV (the user's own only), streamed in chunks. */
    public function export(Request $request): StreamedResponse
    {
        $this->authorize('viewAny', Trade::class);
        $filters = $request->validate(['format' => ['required', 'in:csv']] + self::historyFilters());
        $query = $this->closedTrades($request, $filters)->orderBy('exit_time')->orderBy('id');
        $this->audit->record('history.exported', actor: $request->user(), targetType: 'user', targetId: $request->user()->id,
            details: array_filter($filters + ['rows' => (clone $query)->count()], fn ($v) => $v !== null));
        $text = fn (?string $v) => $v !== null && preg_match('/^[=+\-@\t\r]/', $v) ? "'".$v : $v; // no spreadsheet formulas

        return response()->streamDownload(function () use ($query, $text) {
            $out = fopen('php://output', 'w');
            fputcsv($out, self::EXPORT_COLUMNS);
            foreach ($query->lazy(500) as $t) {
                /** @var Trade $t */
                fputcsv($out, [
                    $t->entry_time?->toIso8601String(),
                    $t->exit_time?->toIso8601String(),
                    $text($t->account?->label),
                    $t->account?->environment->value,
                    $text($t->symbol),
                    $text($t->version?->strategy?->name),
                    $t->contract_type ?? $t->contract_family,
                    $t->side,
                    $t->stake ?? $t->volume,
                    $t->entry_spot ?? $t->entry_price,
                    $t->exit_spot ?? $t->exit_price,
                    $t->fees ?? $t->commission,
                    $t->payout,
                    $t->net_pnl,
                    $t->outcome,
                    self::heldSeconds($t),
                ]);
            }
            fclose($out);
        }, '2kpilot-history-'.now()->format('Ymd').'.csv', ['Content-Type' => 'text/csv; charset=UTF-8']);
    }

    private static function historyFilters(): array
    {
        return [
            'account_id' => ['nullable', 'uuid'],
            'strategy_id' => ['nullable', 'uuid'],
            'symbol' => ['nullable', 'string', 'max:40'],
            'from' => ['nullable', 'date'],
            'to' => ['nullable', 'date'],
            'outcome' => ['nullable', 'in:win,loss,even'],
        ];
    }

    /** The user's closed trades, filtered on exit time ("to" as a plain date includes that whole day). */
    private function closedTrades(Request $request, array $filters): Builder
    {
        $to = isset($filters['to']) ? Carbon::parse($filters['to']) : null;
        if ($to && strlen($filters['to']) === 10) {
            $to = $to->endOfDay();
        }

        return Trade::query()->ownedBy($request->user())->with('account:id,label,environment,currency', 'version.strategy:id,name')
            ->where('status', 'CLOSED')
            ->when($filters['account_id'] ?? null, fn ($q, $id) => $q->where('account_id', $id))
            ->when($filters['symbol'] ?? null, fn ($q, $s) => $q->where('symbol', $s))
            ->when($filters['strategy_id'] ?? null, fn ($q, $id) => $q->whereIn('strategy_version_id', StrategyVersion::query()->where('strategy_id', $id)->select('id')))
            ->when($filters['from'] ?? null, fn ($q, $from) => $q->where('exit_time', '>=', Carbon::parse($from)))
            ->when($to, fn ($q) => $q->where('exit_time', '<=', $to))
            ->when($filters['outcome'] ?? null, fn ($q, $outcome) => $q->where('net_pnl', ['win' => '>', 'loss' => '<', 'even' => '='][$outcome], 0));
    }

    /** The full decision chain of one trade, for the journal drawer. */
    public function trade(Trade $trade): JsonResponse
    {
        $this->authorize('view', $trade);
        $trade->load('account:id,label,environment,currency', 'version.strategy:id,name');
        $signal = $trade->signal_id ? Signal::query()->find($trade->signal_id) : null;
        $evaluation = ($signal && $signal->assignment_id)
            ? StrategyEvaluation::query()->where('assignment_id', $signal->assignment_id)->where('bar_time', $signal->bar_time)->first()
            : null;
        $events = TradeEvent::query()
            ->where(fn ($q) => $q->where('trade_id', $trade->id)->when($signal, fn ($q2) => $q2->orWhere('signal_id', $signal->id)))
            ->orderBy('id')->get();

        return response()->json([
            'trade' => self::present($trade),
            'signal' => $signal,
            'evaluation' => $evaluation,
            'orders' => Order::query()
                ->where(fn ($q) => $q->where('trade_id', $trade->id)->when($signal, fn ($q2) => $q2->orWhere('signal_id', $signal->id)))
                ->orderBy('created_at')->get(),
            'events' => $events,
        ]);
    }

    public function journal(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $events = TradeEvent::query()->ownedBy($request->user())
            ->when($request->query('account_id'), fn ($q, $id) => $q->where('account_id', $id))
            ->when($request->query('type'), fn ($q, $t) => $q->where('event_type', $t))
            ->when($request->query('signal_id'), fn ($q, $s) => $q->where('signal_id', $s))
            ->orderByDesc('id')->paginate(min(200, (int) $request->query('per_page', 100)));

        return response()->json($events);
    }

    public function signals(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $signals = Signal::query()->ownedBy($request->user())->with('account:id,label,environment', 'version.strategy:id,name')
            ->when($request->query('account_id'), fn ($q, $id) => $q->where('account_id', $id))
            ->when($request->query('status'), fn ($q, $s) => $q->where('status', $s))
            ->when($request->query('source'), fn ($q, $s) => $q->where('source', $s))
            ->orderByDesc('created_at')->paginate(min(100, (int) $request->query('per_page', 50)));

        return response()->json($signals);
    }

    public static function present(Trade $t): array
    {
        return [
            'id' => $t->id,
            'account' => $t->account ? ['id' => $t->account->id, 'label' => $t->account->label, 'environment' => $t->account->environment->value, 'currency' => $t->account->currency] : null,
            'strategy' => $t->version?->strategy?->name,
            'strategy_version' => $t->version?->version,
            'source' => $t->strategy_version_id ? 'STRATEGY' : ($t->signal_id ? 'MANUAL' : 'EXTERNAL'),
            'symbol' => $t->symbol,
            'side' => $t->side,
            'status' => $t->status,
            'volume' => $t->volume,
            'entry_price' => $t->entry_price,
            'entry_time' => $t->entry_time?->toIso8601String(),
            'stop_loss' => $t->stop_loss,
            'take_profit' => $t->take_profit,
            'initial_stop_loss' => $t->initial_stop_loss,
            'risk_amount' => $t->risk_amount,
            'exit_price' => $t->exit_price,
            'exit_time' => $t->exit_time?->toIso8601String(),
            'exit_reason' => $t->exit_reason,
            'gross_pnl' => $t->gross_pnl,
            'commission' => $t->commission,
            'swap' => $t->swap,
            'net_pnl' => $t->net_pnl,
            'unrealized_pnl' => $t->unrealized_pnl,
            'r_multiple' => $t->r_multiple,
            'slippage_pips' => $t->slippage_pips,
            'session' => $t->session,
            'is_simulated' => $t->is_simulated,
            'contract_family' => $t->contract_family,
            'contract_type' => $t->contract_type,
            'broker_contract_id' => $t->broker_contract_id,
            'stake' => $t->stake,
            'payout' => $t->payout,
            'multiplier' => $t->multiplier,
            'duration' => $t->duration,
            'duration_unit' => $t->duration_unit,
            'expires_at' => $t->expires_at?->toIso8601String(),
            'entry_spot' => $t->entry_spot,
            'exit_spot' => $t->exit_spot,
            'fees' => $t->fees,
            'outcome' => $t->outcome,
            'longcode' => $t->longcode,
            'duration_seconds' => self::heldSeconds($t),
        ];
    }

    /** How long the trade was (or has been) held. */
    private static function heldSeconds(Trade $t): ?int
    {
        return $t->entry_time ? (int) $t->entry_time->diffInSeconds($t->exit_time ?? now(), true) : null;
    }
}
