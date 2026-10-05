<?php

namespace App\Http\Controllers\Api;

use App\Enums\AuditOutcome;
use App\Http\Controllers\Controller;
use App\Models\Trade;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class PositionController extends Controller
{
    public function __construct(private readonly EngineClient $engine, private readonly AuditLogger $audit) {}

    public function index(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $request->validate(['account_id' => ['nullable', 'uuid']]);
        $positions = Trade::query()->with('account:id,label,environment,currency', 'version.strategy:id,name')
            ->where('status', 'OPEN')
            ->when($request->query('account_id'), fn ($q, $id) => $q->where('account_id', $id))
            ->orderByDesc('entry_time')->get();

        return response()->json($positions->map(fn (Trade $t) => RecordsController::present($t)));
    }

    public function close(Request $request, Trade $trade): JsonResponse
    {
        $this->authorize('trade', $trade->account);
        $request->validate(['confirm' => ['accepted']]);
        try {
            $result = $this->engine->post("/internal/positions/{$trade->id}/close", ['actor_label' => $request->user()->email], 60);
        } catch (EngineException $e) {
            $this->audit->record('position.closed_manually', AuditOutcome::Failure, $request->user(), 'trade', $trade->id, ['reason' => $e->getMessage()]);
            throw $e;
        }
        $this->audit->record('position.closed_manually', actor: $request->user(), targetType: 'trade', targetId: $trade->id,
            details: ['symbol' => $trade->symbol, 'order_status' => $result['order_status'] ?? null]);

        return response()->json($result);
    }

    public function update(Request $request, Trade $trade): JsonResponse
    {
        $this->authorize('trade', $trade->account);
        $data = $request->validate([
            'stop_loss' => ['required', 'numeric', 'gt:0'], // a stop loss can be moved, never removed
            'take_profit' => ['nullable', 'numeric', 'gt:0'],
        ]);
        $payload = ['stop_loss' => (string) $data['stop_loss'], 'take_profit' => isset($data['take_profit']) ? (string) $data['take_profit'] : null, 'actor_label' => $request->user()->email];
        $result = $this->engine->put("/internal/positions/{$trade->id}", $payload);
        $this->audit->record('position.modified_manually', actor: $request->user(), targetType: 'trade', targetId: $trade->id,
            details: ['stop_loss' => $payload['stop_loss'], 'take_profit' => $payload['take_profit']]);

        return response()->json($result);
    }
}
