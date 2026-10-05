<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Order;
use App\Models\Signal;
use App\Models\StrategyEvaluation;
use App\Models\Trade;
use App\Models\TradeEvent;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

/** Orders, trade history, the journal and signals — read-only views of stored records. */
class RecordsController extends Controller
{
    public function orders(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $orders = Order::query()->with('account:id,label,environment')
            ->when($request->query('account_id'), fn ($q, $id) => $q->where('account_id', $id))
            ->when($request->query('status'), fn ($q, $s) => $q->where('status', $s))
            ->orderByDesc('created_at')->paginate(min(100, (int) $request->query('per_page', 50)));

        return response()->json($orders);
    }

    public function history(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $trades = Trade::query()->with('account:id,label,environment,currency', 'version.strategy:id,name')
            ->where('status', 'CLOSED')
            ->when($request->query('account_id'), fn ($q, $id) => $q->where('account_id', $id))
            ->when($request->query('symbol'), fn ($q, $s) => $q->where('symbol', $s))
            ->orderByDesc('exit_time')->paginate(min(100, (int) $request->query('per_page', 50)));
        $trades->getCollection()->transform(fn (Trade $t) => self::present($t));

        return response()->json($trades);
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
        $events = TradeEvent::query()
            ->when($request->query('account_id'), fn ($q, $id) => $q->where('account_id', $id))
            ->when($request->query('type'), fn ($q, $t) => $q->where('event_type', $t))
            ->when($request->query('signal_id'), fn ($q, $s) => $q->where('signal_id', $s))
            ->orderByDesc('id')->paginate(min(200, (int) $request->query('per_page', 100)));

        return response()->json($events);
    }

    public function signals(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $signals = Signal::query()->with('account:id,label,environment', 'version.strategy:id,name')
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
        ];
    }
}
