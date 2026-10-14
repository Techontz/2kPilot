<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Services\Analytics\PerformanceService;
use App\Services\Analytics\StrategyScorecard;
use Carbon\CarbonImmutable;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

class AnalyticsController extends Controller
{
    public function __construct(
        private readonly PerformanceService $performance,
        private readonly StrategyScorecard $scorecard,
    ) {}

    public function performance(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $data = $request->validate([
            'account_id' => ['nullable', 'uuid'],
            'environment' => ['nullable', Rule::in(['PAPER', 'DEMO', 'LIVE'])],
            'period' => ['nullable', Rule::in(['7d', '30d', '90d', '365d', 'all'])],
        ]);
        $since = match ($data['period'] ?? 'all') {
            '7d' => CarbonImmutable::now()->subDays(7),
            '30d' => CarbonImmutable::now()->subDays(30),
            '90d' => CarbonImmutable::now()->subDays(90),
            '365d' => CarbonImmutable::now()->subDays(365),
            default => null,
        };

        return response()->json($this->performance->performance($request->user(), $data['account_id'] ?? null, $data['environment'] ?? null, $since));
    }

    /** Each strategy's real results on one account, with an honest verdict. */
    public function scorecard(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Trade::class);
        $data = $request->validate(['account_id' => ['required', 'uuid']]);
        $account = TradingAccount::query()->ownedBy($request->user())->whereKey($data['account_id'])->firstOrFail();

        return response()->json([
            'account_id' => $account->id,
            'simulated' => $account->isPaper(),
            'min_trades' => StrategyScorecard::MIN_TRADES,
            'rows' => $this->scorecard->for($account),
        ]);
    }
}
