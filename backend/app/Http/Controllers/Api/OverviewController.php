<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\TradingAccount;
use App\Services\Analytics\OverviewService;
use App\Services\Trading\TradingControl;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class OverviewController extends Controller
{
    public function __construct(private readonly OverviewService $overview, private readonly TradingControl $control) {}

    public function show(Request $request): JsonResponse
    {
        $this->authorize('viewAny', TradingAccount::class);
        $request->validate(['account_id' => ['nullable', 'uuid']]);
        $account = $request->query('account_id')
            ? TradingAccount::query()->findOrFail($request->query('account_id'))
            : TradingAccount::query()->orderBy('created_at')->first();
        if ($account === null) {
            return response()->json(['account' => null, 'robot' => $this->control->status()->toArray()]);
        }

        return response()->json($this->overview->forAccount($account));
    }
}
