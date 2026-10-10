<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Http\Resources\AccountResource;
use App\Models\TradingAccount;
use App\Services\Brokers\BrokerService;
use App\Services\Engine\EngineClient;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class AccountController extends Controller
{
    public function __construct(private readonly BrokerService $brokers, private readonly EngineClient $engine) {}

    public function index(Request $request): JsonResponse
    {
        $this->authorize('viewAny', TradingAccount::class);
        $accounts = TradingAccount::query()->ownedBy($request->user())
            ->with(['connection', 'riskProfile', 'assignments.strategy'])
            ->orderBy('created_at')->get();

        return response()->json(AccountResource::collection($accounts));
    }

    public function show(TradingAccount $account): JsonResponse
    {
        $this->authorize('view', $account);

        return response()->json(new AccountResource($account->load('connection', 'riskProfile', 'assignments.strategy')));
    }

    public function update(Request $request, TradingAccount $account): JsonResponse
    {
        $this->authorize('update', $account);
        $data = $request->validate([
            'label' => ['sometimes', 'string', 'max:120'],
            'trading_enabled' => ['sometimes', 'boolean'],
            'risk_profile_id' => ['sometimes', 'nullable', 'uuid', 'exists:risk_profiles,id'],
        ]);
        $account = $this->brokers->updateAccount($account, $request->user(), $data);

        return response()->json(new AccountResource($account->load('connection', 'riskProfile', 'assignments.strategy')));
    }

    /** Refresh balance/equity from the broker now. */
    public function sync(TradingAccount $account): JsonResponse
    {
        $this->authorize('trade', $account); // reaches the broker: the owner only
        $this->engine->post("/internal/accounts/{$account->id}/sync");

        return response()->json(new AccountResource($account->fresh()->load('connection', 'riskProfile', 'assignments.strategy')));
    }
}
