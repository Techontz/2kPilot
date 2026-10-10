<?php

namespace App\Http\Controllers\Api;

use App\Enums\TradingMode;
use App\Http\Controllers\Controller;
use App\Services\Trading\TradingControl;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

/**
 * The current user's STOP TRADING / Resume, operating mode, and the separate
 * "Close positions" action. Everything here acts on the user's own accounts.
 */
class TradingController extends Controller
{
    public function __construct(private readonly TradingControl $control) {}

    public function status(Request $request): JsonResponse
    {
        return response()->json($this->control->status($request->user())->toArray());
    }

    public function stop(Request $request): JsonResponse
    {
        $data = $request->validate(['reason' => ['nullable', 'string', 'max:300']]);
        $this->control->stop($request->user(), $data['reason'] ?? 'Stopped from the dashboard');

        return $this->status($request);
    }

    public function resume(Request $request): JsonResponse
    {
        // `live: true` = the user saw and confirmed the LIVE (real-money) wording.
        $data = $request->validate(['confirm' => ['accepted'], 'live' => ['sometimes', 'boolean']]);
        $this->control->resume($request->user(), (bool) ($data['live'] ?? false));

        return $this->status($request);
    }

    public function mode(Request $request): JsonResponse
    {
        $data = $request->validate([
            'mode' => ['required', Rule::enum(TradingMode::class)],
            'password' => ['nullable', 'string', 'max:200'],
            'mfa_code' => ['nullable', 'string', 'max:20'], // a fresh two-factor code (LIVE only)
            'confirmation_phrase' => ['nullable', 'string', 'max:100'],
            'account_id' => ['nullable', 'uuid'], // the LIVE account whose limits are being authorised
        ]);
        $this->control->setMode($request->user(), TradingMode::from($data['mode']),
            $data['password'] ?? null, $data['confirmation_phrase'] ?? null, $data['account_id'] ?? null, $data['mfa_code'] ?? null);

        return $this->status($request);
    }

    public function closePositions(Request $request): JsonResponse
    {
        $data = $request->validate([
            'confirm' => ['accepted'],
            'reason' => ['nullable', 'string', 'max:300'],
        ]);
        $result = $this->control->closeAllPositions($request->user(), $data['reason'] ?? 'Close positions from the dashboard');

        return response()->json($result + ['status' => $this->control->status($request->user())->toArray()]);
    }
}
