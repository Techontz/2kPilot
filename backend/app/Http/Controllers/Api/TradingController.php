<?php

namespace App\Http\Controllers\Api;

use App\Enums\TradingMode;
use App\Http\Controllers\Controller;
use App\Services\Trading\TradingControl;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Gate;
use Illuminate\Validation\Rule;

/** STOP TRADING / Resume, operating mode, and the separate "Close positions" action. */
class TradingController extends Controller
{
    public function __construct(private readonly TradingControl $control) {}

    public function status(): JsonResponse
    {
        return response()->json($this->control->status()->toArray());
    }

    public function stop(Request $request): JsonResponse
    {
        Gate::authorize('operate-trading');
        $data = $request->validate(['reason' => ['nullable', 'string', 'max:300']]);
        $this->control->stop($request->user(), $data['reason'] ?? 'Stopped from the dashboard');

        return $this->status();
    }

    public function resume(Request $request): JsonResponse
    {
        Gate::authorize('operate-trading');
        $request->validate(['confirm' => ['accepted']]);
        $this->control->resume($request->user());

        return $this->status();
    }

    public function mode(Request $request): JsonResponse
    {
        Gate::authorize('operate-trading');
        $data = $request->validate([
            'mode' => ['required', Rule::enum(TradingMode::class)],
            'password' => ['nullable', 'string', 'max:200'],
            'confirmation_phrase' => ['nullable', 'string', 'max:100'],
        ]);
        $this->control->setMode($request->user(), TradingMode::from($data['mode']), $data['password'] ?? null, $data['confirmation_phrase'] ?? null);

        return $this->status();
    }

    public function closePositions(Request $request): JsonResponse
    {
        Gate::authorize('operate-trading');
        $data = $request->validate([
            'confirm' => ['accepted'],
            'reason' => ['nullable', 'string', 'max:300'],
        ]);
        $result = $this->control->closeAllPositions($request->user(), $data['reason'] ?? 'Close positions from the dashboard');

        return response()->json($result + ['status' => $this->control->status()->toArray()]);
    }
}
