<?php

namespace App\Http\Controllers\Api;

use App\Enums\AuditOutcome;
use App\Http\Controllers\Controller;
use App\Models\TradingAccount;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

/**
 * Manual trading. Laravel authenticates, authorises and audits; the engine
 * runs the SAME risk engine and execution engine as the robot. There is no
 * path that skips risk validation.
 */
class TradeController extends Controller
{
    public function __construct(private readonly EngineClient $engine, private readonly AuditLogger $audit) {}

    public function preview(Request $request): JsonResponse
    {
        [$account, $ticket] = $this->ticket($request, preview: true);

        return response()->json($this->engine->post('/internal/orders/preview', $ticket));
    }

    public function submit(Request $request): JsonResponse
    {
        [$account, $ticket] = $this->ticket($request, preview: false);
        $result = $this->engine->post('/internal/orders', $ticket, 60);
        $this->audit->record('trade.manual_ticket',
            $result['status'] === 'EXECUTED' ? AuditOutcome::Success : ($result['status'] === 'REJECTED' ? AuditOutcome::Denied : AuditOutcome::Failure),
            $request->user(), 'trading_account', $account->id, [
                'symbol' => $ticket['symbol'], 'side' => $ticket['side'], 'volume' => $ticket['volume'],
                'result' => $result['status'], 'reason' => $result['rejection_reason'] ?? null,
                'environment' => $account->environment->value,
            ]);

        return response()->json($result);
    }

    /** @return array{0: TradingAccount, 1: array} */
    private function ticket(Request $request, bool $preview): array
    {
        $data = $request->validate([
            'account_id' => ['required', 'uuid'],
            'symbol' => ['required', 'string', 'max:40'],
            'side' => ['required', Rule::in(['BUY', 'SELL'])],
            'order_type' => ['nullable', Rule::in(['MARKET', 'LIMIT', 'STOP'])],
            'volume' => [$preview ? 'nullable' : 'required', 'numeric', 'gt:0', 'max:100000'],
            'stop_loss' => ['required', 'numeric', 'gt:0'], // a stop loss is always required
            'take_profit' => ['nullable', 'numeric', 'gt:0'],
            'idempotency_key' => [$preview ? 'nullable' : 'required', 'string', 'min:16', 'max:64', 'regex:/^[A-Za-z0-9_-]+$/'],
            'confirm' => [$preview ? 'nullable' : 'accepted'],
        ]);
        $account = TradingAccount::query()->findOrFail($data['account_id']);
        $this->authorize('trade', $account);

        return [$account, array_filter([
            'account_id' => $account->id,
            'symbol' => $data['symbol'],
            'side' => $data['side'],
            'order_type' => $data['order_type'] ?? 'MARKET',
            'volume' => isset($data['volume']) ? (string) $data['volume'] : null,
            'stop_loss' => (string) $data['stop_loss'],
            'take_profit' => isset($data['take_profit']) ? (string) $data['take_profit'] : null,
            'idempotency_key' => $data['idempotency_key'] ?? null,
            'actor_id' => $request->user()->id,
            'actor_label' => $request->user()->email,
        ], fn ($v) => $v !== null)];
    }
}
