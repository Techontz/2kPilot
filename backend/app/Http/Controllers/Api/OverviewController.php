<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\TradingAccount;
use App\Services\Analytics\OverviewService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class OverviewController extends Controller
{
    public function __construct(private readonly OverviewService $overview) {}

    public function show(Request $request): JsonResponse
    {
        $this->authorize('viewAny', TradingAccount::class);
        $request->validate(['account_id' => ['nullable', 'uuid']]);
        $user = $request->user();
        $account = $request->query('account_id')
            ? TradingAccount::query()->ownedBy($user)->findOrFail($request->query('account_id'))
            : TradingAccount::query()->ownedBy($user)->orderBy('created_at')->first();
        if ($account === null) {
            return response()->json($this->overview->withoutAccount($user));
        }

        return response()->json($this->overview->forAccount($account, $user));
    }
}
