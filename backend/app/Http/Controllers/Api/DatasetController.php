<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Dataset;
use App\Models\TradingAccount;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Validation\Rule;
use Illuminate\Validation\ValidationException;

/** Historical data for backtests: CSV import, broker download, or labelled SYNTHETIC data. */
class DatasetController extends Controller
{
    private const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'];

    /**
     * Short candles make many bars: at most ≈100k per dataset (other
     * timeframes: 10 years). The same caps bound broker downloads.
     */
    private const SYNTHETIC_MAX_DAYS = ['M1' => 60, 'M5' => 365];

    private const DEFAULT_MAX_DAYS = 3650;

    public function __construct(private readonly EngineClient $engine, private readonly AuditLogger $audit) {}

    public function index(Request $request): JsonResponse
    {
        $this->authorize('viewAny', Dataset::class);

        return response()->json(Dataset::query()->visibleTo($request->user())->orderBy('symbol')->orderBy('timeframe')->get());
    }

    public function synthetic(Request $request): JsonResponse
    {
        $this->authorize('create', Dataset::class);
        $maxDays = self::maxDays($request->input('timeframe'));
        $data = $request->validate([
            'symbol' => ['required', 'string', 'max:20'],
            'timeframe' => ['required', Rule::in(self::TIMEFRAMES)],
            'days' => ['required', 'integer', "between:30,{$maxDays}"],
            'seed' => ['nullable', 'integer', 'min:0'],
        ]);
        $result = $this->engine->post('/internal/datasets/synthetic', $data + ['seed' => 42, 'user_id' => $request->user()->id], 300);
        $this->audit->record('data.synthetic_generated', actor: $request->user(), targetType: 'dataset', targetId: $result['id'], details: $data);

        return response()->json(Dataset::query()->findOrFail($result['id']), 201);
    }

    public function import(Request $request): JsonResponse
    {
        $this->authorize('create', Dataset::class);
        $data = $request->validate([
            'file' => ['required', 'file', 'max:51200', 'mimetypes:text/plain,text/csv,application/csv,application/vnd.ms-excel'],
            'symbol' => ['required', 'string', 'max:20'],
            'timeframe' => ['required', Rule::in(self::TIMEFRAMES)],
            'utc_offset_hours' => ['nullable', 'numeric', 'between:-14,14'],
        ]);
        $file = $request->file('file');
        $result = $this->engine->post('/internal/datasets/import', [
            'symbol' => $data['symbol'],
            'timeframe' => $data['timeframe'],
            'content' => (string) file_get_contents($file->getRealPath()),
            'utc_offset_hours' => (float) ($data['utc_offset_hours'] ?? 0),
            'filename' => mb_substr($file->getClientOriginalName(), 0, 200),
            'user_id' => $request->user()->id,
        ], 300);
        $this->audit->record('data.imported', actor: $request->user(), targetType: 'dataset', targetId: $result['id'],
            details: ['symbol' => $data['symbol'], 'timeframe' => $data['timeframe']]);

        return response()->json(['dataset' => Dataset::query()->findOrFail($result['id']), 'report' => $result['report']], 201);
    }

    public function download(Request $request): JsonResponse
    {
        $this->authorize('create', Dataset::class);
        $data = $request->validate([
            'account_id' => ['required', 'uuid'],
            'symbol' => ['required', 'string', 'max:40'],
            'timeframe' => ['required', Rule::in(self::TIMEFRAMES)],
            'start' => ['required', 'date'],
            'end' => ['required', 'date', 'after:start', 'before_or_equal:now'],
        ]);
        // A bounded span keeps the broker download (and the engine call) short.
        $maxDays = self::maxDays($data['timeframe']);
        if (Carbon::parse($data['start'])->diffInDays(Carbon::parse($data['end'])) > $maxDays) {
            throw ValidationException::withMessages(['start' => "At most {$maxDays} days of {$data['timeframe']} candles per download. Choose a later start date."]);
        }
        $this->authorize('trade', TradingAccount::query()->ownedBy($request->user())->findOrFail($data['account_id']));
        $result = $this->engine->post('/internal/datasets/download', $data + ['user_id' => $request->user()->id], 600);
        $this->audit->record('data.downloaded', actor: $request->user(), targetType: 'dataset', targetId: $result['id'], details: $data);

        return response()->json(Dataset::query()->findOrFail($result['id']), 201);
    }

    private static function maxDays(mixed $timeframe): int
    {
        return self::SYNTHETIC_MAX_DAYS[(string) $timeframe] ?? self::DEFAULT_MAX_DAYS;
    }

    public function destroy(Request $request, Dataset $dataset): JsonResponse
    {
        $this->authorize('delete', $dataset);
        $this->audit->record('data.deleted', actor: $request->user(), targetType: 'dataset', targetId: $dataset->id,
            details: ['symbol' => $dataset->symbol, 'timeframe' => $dataset->timeframe]);
        $dataset->delete(); // candles cascade

        return response()->json(['ok' => true]);
    }
}
