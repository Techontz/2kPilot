<?php

namespace App\Http\Controllers\Api;

use App\Enums\AssignmentStatus;
use App\Enums\AuditOutcome;
use App\Exceptions\DomainException;
use App\Http\Controllers\Controller;
use App\Http\Requests\ActivateStrategyRequest;
use App\Http\Requests\DraftStrategyRequest;
use App\Http\Requests\ImportStrategyRequest;
use App\Http\Requests\StoreStrategyRequest;
use App\Http\Requests\UpdateStrategyRequest;
use App\Models\Backtest;
use App\Models\Signal;
use App\Models\Strategy;
use App\Models\StrategyAssignment;
use App\Models\StrategyEvaluation;
use App\Models\StrategyVersion;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Models\User;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use App\Services\Strategies\StrategyService;
use App\Services\Trading\Blockers;
use App\Support\ContractSpec;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Support\Str;
use Illuminate\Validation\Rule;

class StrategyController extends Controller
{
    public function __construct(
        private readonly StrategyService $strategies,
        private readonly EngineClient $engine,
        private readonly AuditLogger $audit,
        private readonly Blockers $blockers,
    ) {}

    /**
     * Built-in templates (shared) and the user's own strategies. Results are the
     * user's own only: demo performance (PAPER/DEMO accounts), LIVE performance
     * kept separate, and the latest completed backtest. Archived strategies are
     * hidden unless ?archived=1.
     */
    public function index(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Strategy::class);
        $user = $request->user();
        $catalog = collect($this->strategies->catalog())->keyBy('key');
        $strategies = Strategy::query()->visibleTo($user)
            ->when(! $request->boolean('archived'), fn ($q) => $q->active())
            ->with('versions')->orderByRaw('user_id IS NULL DESC')->orderBy('name')->get();

        return response()->json($strategies->map(function (Strategy $s) use ($catalog, $user) {
            $versionIds = $s->versions->pluck('id');
            $latest = $s->versions->sortByDesc('version')->first();
            $closed = Trade::query()->ownedBy($user)->whereIn('strategy_version_id', $versionIds)->where('status', 'CLOSED')->whereNotNull('net_pnl');
            $backtest = Backtest::query()->ownedBy($user)->whereIn('strategy_version_id', $versionIds)->whereNull('parent_id')
                ->where('status', 'COMPLETED')->latest('finished_at')->first();

            return [
                'id' => $s->id,
                'key' => $s->key,
                'slug' => $s->slug,
                'name' => $s->name,
                'description' => $s->description,
                'summary' => $s->summary,
                'details' => $s->details,
                'source' => $s->source,
                'built_in' => $s->isShared(),
                'editable' => $user->can('update', $s),
                'archived' => $s->archived_at !== null,
                'copied_from_id' => $s->copied_from_id,
                'code_version' => $catalog[$s->key]['code_version'] ?? null,
                // Rule-based strategies use the builder catalogue instead (GET /api/strategies/catalog).
                'parameter_schema' => $s->isRules() ? null : ($catalog[$s->key]['parameter_schema'] ?? null),
                // null = any market / contract family.
                'contract_families' => $catalog[$s->key]['contract_families'] ?? ($s->details['supported_contract_families'] ?? null),
                'symbols' => $catalog[$s->key]['symbols'] ?? ($s->details['supported_symbols'] ?? null),
                'entries_disabled' => $this->entriesDisabled($s),
                'latest_version' => $latest ? self::version($latest) : null,
                'rules_text' => $latest?->rules_text,
                'versions' => $s->versions->map(fn (StrategyVersion $v) => self::version($v))->values(),
                'assignments' => StrategyAssignment::query()->ownedBy($user)->with('account:id,label,environment,connection_id', 'account.connection:id,connector_type', 'version:id,version')
                    ->where('strategy_id', $s->id)->get()->map(fn ($a) => self::assignment($a)),
                'performance' => $this->performance($user, $versionIds->all()),
                'backtest' => $backtest ? self::backtestHeadline($backtest) : null,
                // The latest completed backtest per market: results by instrument.
                'backtests_by_symbol' => Backtest::query()->ownedBy($user)->whereIn('strategy_version_id', $versionIds)->whereNull('parent_id')
                    ->where('status', 'COMPLETED')->latest('finished_at')->limit(30)->get()->unique('symbol')->values()
                    ->map(fn (Backtest $b) => self::backtestHeadline($b)),
                // Kept for older dashboards: every closed trade of this strategy (all environments).
                'live_trades' => (clone $closed)->count(),
                'live_net_pnl' => round((float) (clone $closed)->sum('net_pnl'), 2),
                'last_backtest' => $backtest ? ['id' => $backtest->id, 'status' => $backtest->status->value, 'metrics' => $backtest->metrics] : null,
            ];
        }));
    }

    /** Indicators, operators, price fields and limits for the rule builder. */
    public function catalog(): JsonResponse
    {
        $this->authorize('viewAny', Strategy::class);

        return response()->json($this->strategies->rulesCatalog());
    }

    /** A new strategy from the visual builder (or a reviewed AI draft / import): version 1. */
    public function store(StoreStrategyRequest $request): JsonResponse
    {
        $data = $request->validated();
        $strategy = $this->strategies->createRules($request->user(), $data['name'], (string) ($data['description'] ?? ''),
            $data['rules'], $data['source'] ?? 'builder');

        return response()->json(self::detail($strategy), 201);
    }

    public function update(UpdateStrategyRequest $request, Strategy $strategy): JsonResponse
    {
        $data = $request->validated();
        if (array_key_exists('description', $data)) {
            $data['description'] = (string) $data['description'];
        }
        $strategy = $this->strategies->rename($strategy, $data, $request->user());

        return response()->json(self::detail($strategy));
    }

    /** Delete (or archive, when trades/signals/backtests reference it). Refused while enabled. */
    public function destroy(Request $request, Strategy $strategy): JsonResponse
    {
        $this->authorize('delete', $strategy);
        $outcome = $this->strategies->remove($strategy, $request->user());

        return response()->json(['ok' => true, 'outcome' => $outcome]);
    }

    /** Download a rule-based strategy as a JSON file (the import format). */
    public function export(Request $request, Strategy $strategy): JsonResponse
    {
        $this->authorize('view', $strategy);
        if (! $strategy->isRules()) {
            throw new DomainException('Only rule-based strategies can be exported.', 422, 'not_exportable');
        }
        $latest = $strategy->versions()->reorder('version', 'desc')->firstOrFail();
        $file = Str::slug($strategy->name) ?: 'strategy';

        return response()->json([
            'format' => 'tradepilot.strategy',
            'schema_version' => (int) ($latest->parameters['schema_version'] ?? 1),
            'name' => $strategy->name,
            'description' => $strategy->description,
            'rules' => $latest->parameters,
        ], 200, ['Content-Disposition' => "attachment; filename=\"{$file}.tradepilot.json\""], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }

    public function import(ImportStrategyRequest $request): JsonResponse
    {
        $data = $request->validated();
        $strategy = $this->strategies->createRules($request->user(), $data['name'], (string) ($data['description'] ?? ''),
            $data['rules'], 'import');

        return response()->json(self::detail($strategy), 201);
    }

    /**
     * Method C: plain English → DRAFT rules (Claude, through the engine). Never
     * saved: the user reviews and edits the draft, then saves it with store().
     * The audit log keeps the description's length and the outcome, not the text.
     */
    public function draft(DraftStrategyRequest $request): JsonResponse
    {
        $data = $request->validated();
        $user = $request->user();
        $details = ['description_length' => mb_strlen($data['description'])];
        try {
            $draft = $this->engine->post('/internal/strategies/draft', array_filter([
                'description' => $data['description'],
                'symbol' => $data['symbol'] ?? null,
                'timeframe' => $data['timeframe'] ?? null,
                'contract_family' => $data['contract_family'] ?? null,
            ], fn ($v) => $v !== null), (int) config('tradepilot.engine.draft_timeout', 300));
        } catch (EngineException $e) {
            $this->audit->record('strategy.ai_draft', AuditOutcome::Failure, $user, details: $details + ['outcome' => $e->errorCode]);
            if ($e->errorCode === 'ai_not_configured') {
                throw new EngineException("Plain-English drafting isn't set up on this server.", 503, 'ai_not_configured');
            }
            throw $e;
        }
        $this->audit->record('strategy.ai_draft', actor: $user, details: $details + [
            'outcome' => ($draft['rules'] ?? null) === null ? 'empty' : 'drafted',
            'unsupported' => count($draft['unsupported'] ?? []),
            'model' => $draft['model'] ?? null,
        ]);

        return response()->json([
            'rules' => $draft['rules'] ?? null,
            'rules_text' => $draft['rules_text'] ?? null,
            'explanation' => $draft['explanation'] ?? '',
            'warnings' => $draft['warnings'] ?? [],
            'unsupported' => $draft['unsupported'] ?? [],
            'notes' => $draft['notes'] ?? [],
            'model' => $draft['model'] ?? null,
        ]);
    }

    public function storeVersion(Request $request, Strategy $strategy): JsonResponse
    {
        $this->authorize('update', $strategy);
        $data = $request->validate([
            'parameters' => ['required_without:rules', 'array', StoreStrategyRequest::sizeLimit()],
            'rules' => ['required_without:parameters', 'array', StoreStrategyRequest::sizeLimit()], // alias for rule-based strategies
            'notes' => ['nullable', 'string', 'max:500'],
        ]);
        if ($strategy->archived_at !== null) {
            throw DomainException::conflict('This strategy is archived.', 'strategy_archived');
        }
        $version = $this->strategies->createVersion($strategy, $data['parameters'] ?? $data['rules'], $data['notes'] ?? '', $request->user());

        return response()->json($version, 201);
    }

    /** Copy a strategy (typically a built-in template) into the user's own strategies. */
    public function copy(Request $request, Strategy $strategy): JsonResponse
    {
        $this->authorize('use', $strategy); // own or built-in: admins cannot copy a user's private strategy
        $this->authorize('create', Strategy::class);
        $data = $request->validate(['name' => ['required', 'string', 'max:120',
            Rule::unique('strategies', 'name')->where('user_id', $request->user()->id)]]);
        $copy = $this->strategies->copy($strategy, $data['name'], $request->user());

        return response()->json($copy->load('versions'), 201);
    }

    /**
     * Run a strategy version on a symbol, with contract fields at the top level
     * (contract_family omitted: Rise/Fall 5 minutes on Deriv, Spot on Paper).
     */
    public function assign(Request $request): JsonResponse
    {
        $this->authorize('create', StrategyAssignment::class);
        $data = $request->validate([
            'strategy_version_id' => ['required', 'uuid'],
            'account_id' => ['required', 'uuid'],
            'symbol' => ['required', 'string', 'max:40'],
        ] + ContractSpec::rules());
        $account = TradingAccount::query()->ownedBy($request->user())->with('connection')->findOrFail($data['account_id']);
        $this->authorize('trade', $account);
        $version = $this->visibleVersion($request, $data['strategy_version_id']);
        $spec = ContractSpec::validate($data, $account);
        $this->strategies->ensureSupported($version->strategy, $data['symbol'], $spec);
        [$contract, $check] = $this->strategies->checkContract($account, $data['symbol'], $spec);
        $assignment = $this->strategies->assign($version, $account, $data['symbol'], $request->user(), $contract);

        return response()->json(self::assignment($assignment->load('account.connection', 'version')) + ['contract_check' => $check], 201);
    }

    /** Change how the assignment's signals are traded. Pauses it, like a version switch. */
    public function updateContract(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('update', $assignment);
        $data = $request->validate(ContractSpec::rules());
        $account = $assignment->account()->with('connection')->firstOrFail();
        $spec = ContractSpec::validate($data, $account);
        $this->strategies->ensureSupported($assignment->strategy()->firstOrFail(), $assignment->symbol, $spec);
        [$contract, $check] = $this->strategies->checkContract($account, $assignment->symbol, $spec);
        $assignment = $this->strategies->changeContract($assignment, $contract, $request->user());

        return response()->json(self::assignment($assignment->load('account.connection', 'version')) + ['contract_check' => $check]);
    }

    public function enable(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('update', $assignment);
        $assignment = $this->strategies->setStatus($assignment, AssignmentStatus::Enabled, $request->user());

        return response()->json(self::assignment($assignment->load('account.connection', 'version')));
    }

    public function pause(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('update', $assignment);
        $data = $request->validate(['reason' => ['nullable', 'string', 'max:300']]);
        $assignment = $this->strategies->setStatus($assignment, AssignmentStatus::Paused, $request->user(), $data['reason'] ?? '');

        return response()->json(self::assignment($assignment->load('account.connection', 'version')));
    }

    public function switchVersion(Request $request, StrategyAssignment $assignment): JsonResponse
    {
        $this->authorize('update', $assignment);
        $data = $request->validate(['strategy_version_id' => ['required', 'uuid']]);
        $assignment = $this->strategies->switchVersion($assignment, $this->visibleVersion($request, $data['strategy_version_id']), $request->user());

        return response()->json(self::assignment($assignment->load('account.connection', 'version')));
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

    /**
     * Run the strategy's latest version on an account + symbol with a contract,
     * and enable it. Creates the assignment or updates the existing one. Every
     * existing rule still applies: the contract is checked against the broker,
     * the account needs a risk profile, and the user's own STOP switch, mode
     * and the platform halt still decide whether anything trades — reported
     * in `blockers` and `status_reason`.
     */
    public function activate(ActivateStrategyRequest $request, Strategy $strategy): JsonResponse
    {
        $user = $request->user();
        $data = $request->validated();
        if ($strategy->archived_at !== null) {
            throw DomainException::conflict('This strategy is archived.', 'strategy_archived');
        }
        $account = TradingAccount::query()->ownedBy($user)->with('connection')->findOrFail($data['account_id']);
        $this->authorize('trade', $account);
        $contract = ContractSpec::validate($request->all(), $account, 'contract.');
        $this->strategies->ensureSupported($strategy, $data['symbol'], $contract);
        [$contract, $check] = $this->strategies->checkContract($account, $data['symbol'], $contract);
        $blockers = [...$this->blockers->controls($user, $account), ...$this->blockers->marketClosed($account, [$data['symbol']])];
        $assignment = $this->strategies->activate($strategy, $account, $data['symbol'], $contract, $user,
            $blockers ? 'Enabled — but nothing will trade until: '.implode(' ', array_column($blockers, 'message')) : '');

        return response()->json(self::assignment($assignment->load('account.connection', 'version')) + [
            'contract_check' => $check,
            'blockers' => $blockers,
            'will_trade' => $blockers === [],
        ]);
    }

    /** Pause this strategy's assignments on one account. */
    public function deactivate(Request $request, Strategy $strategy): JsonResponse
    {
        $this->authorize('view', $strategy);
        $data = $request->validate(['account_id' => ['required', 'uuid'], 'reason' => ['nullable', 'string', 'max:300']]);
        $account = TradingAccount::query()->ownedBy($request->user())->findOrFail($data['account_id']);
        $paused = StrategyAssignment::query()->where('strategy_id', $strategy->id)->where('account_id', $account->id)
            ->where('status', AssignmentStatus::Enabled)->get()
            ->map(fn (StrategyAssignment $a) => $this->strategies->setStatus($a, AssignmentStatus::Paused, $request->user(), $data['reason'] ?? ''));

        return response()->json(['paused' => $paused->count(), 'assignments' => StrategyAssignment::query()->where('strategy_id', $strategy->id)
            ->where('account_id', $account->id)->with('account.connection', 'version')->get()->map(fn ($a) => self::assignment($a))]);
    }

    private static function version(StrategyVersion $v): array
    {
        return [
            'id' => $v->id,
            'version' => $v->version,
            'code_version' => $v->code_version,
            'parameters' => $v->parameters,
            'rules_text' => $v->rules_text,
            'notes' => $v->notes,
            'created_at' => $v->created_at?->toIso8601String(),
        ];
    }

    private static function detail(Strategy $s): array
    {
        $s->load('versions');
        $latest = $s->versions->sortByDesc('version')->first();

        return [
            'id' => $s->id,
            'key' => $s->key,
            'slug' => $s->slug,
            'name' => $s->name,
            'description' => $s->description,
            'summary' => $s->summary,
            'details' => $s->details,
            'source' => $s->source,
            'built_in' => $s->isShared(),
            'archived' => $s->archived_at !== null,
            'copied_from_id' => $s->copied_from_id,
            'latest_version' => $latest ? self::version($latest) : null,
            'rules_text' => $latest?->rules_text,
            'versions' => $s->versions->map(fn (StrategyVersion $v) => self::version($v))->values(),
        ];
    }

    /**
     * The user's own closed trades of these versions: PAPER/DEMO ("demo") and
     * LIVE separately — never mixed, and never another user's trades.
     */
    private function performance(User $user, array $versionIds): array
    {
        $since = now()->subDays(30);
        $rows = Trade::query()->ownedBy($user)
            ->join('trading_accounts', 'trading_accounts.id', '=', 'trades.account_id')
            ->whereIn('trades.strategy_version_id', $versionIds)->where('trades.status', 'CLOSED')->whereNotNull('trades.net_pnl')
            ->selectRaw("CASE WHEN trading_accounts.environment = 'LIVE' THEN 'live' WHEN trading_accounts.environment IN ('PAPER', 'DEMO') THEN 'demo' ELSE 'other' END AS bucket")
            ->selectRaw('COUNT(*) AS trades, SUM(trades.net_pnl > 0) AS wins, SUM(trades.net_pnl) AS net_pnl')
            ->selectRaw('SUM(CASE WHEN trades.exit_time >= ? THEN trades.net_pnl ELSE 0 END) AS net_pnl_30d', [$since])
            ->selectRaw('MAX(trades.exit_time) AS last_trade_at')
            ->groupBy('bucket')->toBase()->get()->keyBy('bucket');
        $stats = function (?object $r): array {
            $n = (int) ($r->trades ?? 0);

            return [
                'trades' => $n,
                'wins' => (int) ($r->wins ?? 0),
                'win_rate' => $n ? round((int) $r->wins / $n * 100, 1) : null,
                'net_pnl' => round((float) ($r->net_pnl ?? 0), 2),
                'net_pnl_30d' => round((float) ($r->net_pnl_30d ?? 0), 2),
                'last_trade_at' => isset($r->last_trade_at) ? Carbon::parse($r->last_trade_at, 'UTC')->toIso8601String() : null,
            ];
        };

        return ['demo' => $stats($rows->get('demo')), 'live' => $rows->has('live') ? $stats($rows->get('live')) : null];
    }

    private static function backtestHeadline(Backtest $b): array
    {
        $m = (array) $b->metrics;

        return [
            'id' => $b->id,
            'name' => $b->name,
            'symbol' => $b->symbol,
            'timeframe' => $b->timeframe,
            'net_pnl' => $m['net_pnl'] ?? null,
            'return_pct' => $m['return_pct'] ?? null,
            'win_rate' => $m['win_rate'] ?? null,
            'trades' => $m['trades'] ?? null,
            'max_drawdown' => $m['max_drawdown'] ?? null,
            'max_drawdown_pct' => $m['max_drawdown_pct'] ?? null,
            'contract_family' => $b->config['contract']['contract_family'] ?? null,
            'run_at' => ($b->finished_at ?? $b->created_at)?->toIso8601String(),
            'kind' => $b->kind,
            'data_source' => $b->data_source,
            'profit_factor' => $m['profit_factor'] ?? null,
            'expectancy' => $m['expectancy'] ?? null,
            'avg_rr' => $m['avg_rr'] ?? null,
            'longest_losing_streak' => $m['longest_losing_streak'] ?? null,
            'by_regime' => $m['by_regime'] ?? [],
            'validation' => ((array) $b->report)['validation'] ?? null,
        ];
    }

    /** The emergency stop on this strategy, or on the built-in it was copied from. */
    private function entriesDisabled(Strategy $s): ?array
    {
        $source = $s->entriesDisabled() ? $s : ($s->copied_from_id ? Strategy::query()->find($s->copied_from_id) : null);
        if ($source === null || ! $source->entriesDisabled()) {
            return null;
        }

        return [
            'at' => $source->entries_disabled_at?->toIso8601String(),
            'reason' => $source->entries_disabled_reason,
            'inherited' => $source->id !== $s->id,
        ];
    }

    /** A version of a strategy the user can see (their own or a built-in one); 404 otherwise. */
    private function visibleVersion(Request $request, string $id): StrategyVersion
    {
        return StrategyVersion::query()->whereHas('strategy', fn ($q) => $q->visibleTo($request->user()))->findOrFail($id);
    }

    public static function assignment(StrategyAssignment $a): array
    {
        return [
            'id' => $a->id,
            'strategy_id' => $a->strategy_id,
            'strategy_version_id' => $a->strategy_version_id,
            'version' => $a->version?->version,
            'account' => $a->account ? [
                'id' => $a->account->id, 'label' => $a->account->label, 'environment' => $a->account->environment->value,
                'connector_type' => $a->account->connection?->connector_type->value,
            ] : null,
            'symbol' => $a->symbol,
            'contract' => ContractSpec::fromAssignment($a),
            'status' => $a->status->value,
            'status_reason' => $a->status_reason,
            'last_bar_evaluated' => $a->last_bar_evaluated?->toIso8601String(),
            'last_signal_at' => $a->last_signal_at?->toIso8601String(),
        ];
    }
}
