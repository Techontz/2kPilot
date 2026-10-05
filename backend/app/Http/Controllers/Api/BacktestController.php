<?php

namespace App\Http\Controllers\Api;

use App\Enums\BacktestStatus;
use App\Exceptions\DomainException;
use App\Http\Controllers\Controller;
use App\Jobs\RunBacktest;
use App\Models\Backtest;
use App\Models\StrategyVersion;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

/**
 * Backtests: the same strategy and risk code as live trading, fills at the
 * next bar's open (no look-ahead), with spread, commission, slippage and swap.
 */
class BacktestController extends Controller
{
    public function __construct(private readonly EngineClient $engine, private readonly AuditLogger $audit) {}

    public function index(): JsonResponse
    {
        $this->authorize('viewAny', Backtest::class);

        return response()->json(Backtest::query()->whereNull('parent_id')->latest('created_at')->limit(100)
            ->get(['id', 'name', 'kind', 'status', 'strategy_key', 'symbol', 'timeframe', 'data_source', 'start', 'end', 'initial_capital', 'progress', 'metrics', 'error', 'created_at', 'finished_at']));
    }

    public function store(Request $request): JsonResponse
    {
        $this->authorize('create', Backtest::class);
        $data = $request->validate([
            'mode' => ['required', Rule::in(['single', 'split', 'walk_forward', 'sensitivity'])],
            'strategy_version_id' => ['required', 'uuid', 'exists:strategy_versions,id'],
            'parameters' => ['nullable', 'array'],
            'dataset_id' => ['required', 'uuid', 'exists:datasets,id'],
            'start' => ['required', 'date'],
            'end' => ['required', 'date', 'after:start'],
            'initial_capital' => ['required', 'numeric', 'gt:0', 'max:100000000'],
            'risk' => ['nullable', 'array'],
            'costs' => ['nullable', 'array'],
            'costs.spread_pips' => ['nullable', 'numeric', 'min:0', 'max:100'],
            'costs.commission_per_lot' => ['nullable', 'numeric', 'min:0', 'max:1000'],
            'costs.slippage_pips' => ['nullable', 'numeric', 'min:0', 'max:100'],
            'name' => ['nullable', 'string', 'max:200'],
            'split_ratio' => ['nullable', 'numeric', 'between:0.3,0.9'],
            'train_months' => ['nullable', 'integer', 'between:1,36'],
            'test_months' => ['nullable', 'integer', 'between:1,12'],
            'grid' => ['nullable', 'array'],
        ]);
        $version = StrategyVersion::query()->with('strategy')->findOrFail($data['strategy_version_id']);
        $created = $this->engine->post('/internal/backtests', array_filter([
            'mode' => $data['mode'],
            'strategy_key' => $version->strategy->key,
            'strategy_version_id' => $version->id,
            'parameters' => (object) array_merge($version->parameters, $data['parameters'] ?? []),
            'dataset_id' => $data['dataset_id'],
            'start' => $data['start'],
            'end' => $data['end'],
            'initial_capital' => (string) $data['initial_capital'],
            'risk' => (object) ($data['risk'] ?? []),
            'costs' => (object) ($data['costs'] ?? []),
            'name' => $data['name'] ?? '',
            'split_ratio' => $data['split_ratio'] ?? null,
            'train_months' => $data['train_months'] ?? null,
            'test_months' => $data['test_months'] ?? null,
            'grid' => isset($data['grid']) ? (object) $data['grid'] : null,
            'actor_id' => $request->user()->id,
        ], fn ($v) => $v !== null));
        RunBacktest::dispatch($created['id']);
        $this->audit->record('backtest.started', actor: $request->user(), targetType: 'backtest', targetId: $created['id'],
            details: ['mode' => $data['mode'], 'strategy' => $version->strategy->key, 'version' => $version->version]);

        return response()->json(Backtest::query()->findOrFail($created['id']), 202);
    }

    public function show(Backtest $backtest): JsonResponse
    {
        $this->authorize('view', $backtest);

        return response()->json($backtest->load('children'));
    }

    public function trades(Request $request, Backtest $backtest): JsonResponse
    {
        $this->authorize('view', $backtest);

        return response()->json($backtest->trades()->limit(min(10000, (int) $request->query('limit', 5000)))->get());
    }

    public function destroy(Request $request, Backtest $backtest): JsonResponse
    {
        $this->authorize('delete', $backtest);
        if (in_array($backtest->status, [BacktestStatus::Queued, BacktestStatus::Running], true)) {
            throw DomainException::conflict('Wait for the backtest to finish before deleting it.');
        }
        $this->audit->record('backtest.deleted', actor: $request->user(), targetType: 'backtest', targetId: $backtest->id,
            details: ['name' => $backtest->name]);
        $backtest->delete();

        return response()->json(['ok' => true]);
    }
}
