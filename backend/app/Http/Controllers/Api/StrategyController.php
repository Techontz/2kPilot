<?php

namespace App\Http\Controllers\Api;

use App\Enums\AssignmentStatus;
use App\Http\Controllers\Controller;
use App\Models\Backtest;
use App\Models\Signal;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\StrategyEvaluation;
use App\Models\StrategyVersion;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Services\Strategies\StrategyService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class StrategyController extends Controller
{
    public function __construct(private readonly StrategyService $strategies) {}

    public function index(): JsonResponse
    {
        $this->authorize('viewAny', Strategy::class);
        $catalog = collect($this->strategies->catalog())->keyBy('key');
        $strategies = Strategy::query()->with('versions')->orderBy('name')->get();

        return response()->json($strategies->map(function (Strategy $s) use ($catalog) {
            $versionIds = $s->versions->pluck('id');
            $closed = Trade::query()->whereIn('strategy_version_id', $versionIds)->where('status', 'CLOSED')->whereNotNull('net_pnl');
            $lastBacktest = Backtest::query()->where('strategy_key', $s->key)->whereNull('parent_id')->latest('created_at')->first();

            return [
                'id' => $s->id,
                'key' => $s->key,
                'name' => $s->name,
                'description' => $s->description,
                'code_version' => $catalog[$s->key]['code_version'] ?? null,
                'parameter_schema' => $catalog[$s->key]['parameter_schema'] ?? null,
                'versions' => $s->versions,
                'assignments' => StrategyAssignment::query()->with('account:id,label,environment', 'version:id,version')
                    ->where('strategy_id', $s->id)->get()->map(fn ($a) => self::assignment($a)),
                'live_trades' => (clone $closed)->count(),
                'live_net_pnl' => round((float) (clone $closed)->sum('net_pnl'), 2),
                'last_backtest' => $lastBacktest ? ['id' => $lastBacktest->id, 'status' => $lastBacktest->status->value, 'metrics' => $lastBacktest->metrics] : null,
            ];
        }));
    }

    public function storeVersion(Request $request, Strategy $strategy): JsonResponse
    {
        $this->authorize('update', $strategy);
        $data = $request->validate(['parameters' => ['required', 'array'], 'notes' => ['nullable', 'string', 'max:500']]);
        $version = $this->strategies->createVersion($strategy, $data['parameters'], $data['notes'] ?? '', $request->user());

        return response()->json($version, 201);
    }

    public function assign(Request $request): JsonResponse
    {
        $this->authorize('create', StrategyAssignment::class);
        $data = $request->validate([
            'strategy_version_id' => ['required', 'uuid', 'exists:strategy_versions,id'],
            'account_id' => ['required', 'uuid', 'exists:trading_accounts,id'],
            'symbol' => ['required', 'string', 'max:40'],
        ]);
        $assignment = $this->strategies->assign(
            StrategyVersion::query()->findOrFail($data['strategy_version_id']),
            TradingAccount::query()->findOrFail($data['account_id']),
            $data['symbol'], $request->user(),
        );

        return response()->json(self::assignment($assignment->load('account', 'version')), 201);
    }

    public function enable(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('update', $assignment);
        $assignment = $this->strategies->setStatus($assignment, AssignmentStatus::Enabled, $request->user());

        return response()->json(self::assignment($assignment->load('account', 'version')));
    }

    public function pause(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('update', $assignment);
        $data = $request->validate(['reason' => ['nullable', 'string', 'max:300']]);
        $assignment = $this->strategies->setStatus($assignment, AssignmentStatus::Paused, $request->user(), $data['reason'] ?? '');

        return response()->json(self::assignment($assignment->load('account', 'version')));
    }

    public function switchVersion(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('update', $assignment);
        $data = $request->validate(['strategy_version_id' => ['required', 'uuid', 'exists:strategy_versions,id']]);
        $assignment = $this->strategies->switchVersion($assignment, StrategyVersion::query()->findOrFail($data['strategy_version_id']), $request->user());

        return response()->json(self::assignment($assignment->load('account', 'version')));
    }

    public function unassign(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('delete', $assignment);
        $this->strategies->unassign($assignment, $request->user());

        return response()->json(['ok' => true]);
    }

    /** Why each closed bar did — or did not — produce a trade. */
    public function evaluations(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('view', $assignment);
        $evaluations = StrategyEvaluation::query()->where('assignment_id', $assignment->id)
            ->when($request->query('outcome'), fn ($q, $o) => $q->where('outcome', $o))
            ->orderByDesc('bar_time')->paginate(min(100, (int) $request->query('per_page', 50)));
        $signals = Signal::query()->where('assignment_id', $assignment->id)->orderByDesc('created_at')->limit(20)
            ->get(['id', 'side', 'bar_time', 'status', 'rejection_reason', 'reasons', 'risk_checks', 'volume', 'risk_amount', 'created_at']);

        return response()->json(['evaluations' => $evaluations, 'signals' => $signals]);
    }

    public static function assignment(StrategyAssignment $a): array
    {
        return [
            'id' => $a->id,
            'strategy_id' => $a->strategy_id,
            'strategy_version_id' => $a->strategy_version_id,
            'version' => $a->version?->version,
            'account' => $a->account ? ['id' => $a->account->id, 'label' => $a->account->label, 'environment' => $a->account->environment->value] : null,
            'symbol' => $a->symbol,
            'status' => $a->status->value,
            'status_reason' => $a->status_reason,
            'last_bar_evaluated' => $a->last_bar_evaluated?->toIso8601String(),
            'last_signal_at' => $a->last_signal_at?->toIso8601String(),
        ];
    }
}
