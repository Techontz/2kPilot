<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Dataset;
use App\Models\TradingAccount;
use App\Services\Audit\AuditLogger;
use App\Services\Engine\EngineClient;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

/** Historical data for backtests: CSV import, broker download, or labelled SYNTHETIC data. */
class DatasetController extends Controller
{
    private const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'];

    public function __construct(private readonly EngineClient $engine, private readonly AuditLogger $audit) {}

    public function index(): JsonResponse
    {
        $this->authorize('viewAny', Dataset::class);

        return response()->json(Dataset::query()->orderBy('symbol')->orderBy('timeframe')->get());
    }

    public function synthetic(Request $request): JsonResponse
    {
        $this->authorize('create', Dataset::class);
        $data = $request->validate([
            'symbol' => ['required', 'string', 'max:20'],
            'timeframe' => ['required', Rule::in(self::TIMEFRAMES)],
            'days' => ['required', 'integer', 'between:30,3650'],
            'seed' => ['nullable', 'integer', 'min:0'],
        ]);
        $result = $this->engine->post('/internal/datasets/synthetic', $data + ['seed' => 42], 300);
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
        ], 300);
        $this->audit->record('data.imported', actor: $request->user(), targetType: 'dataset', targetId: $result['id'],
            details: ['symbol' => $data['symbol'], 'timeframe' => $data['timeframe']]);

        return response()->json(['dataset' => Dataset::query()->findOrFail($result['id']), 'report' => $result['report']], 201);
    }

    public function download(Request $request): JsonResponse
    {
        $this->authorize('create', Dataset::class);
        $data = $request->validate([
            'account_id' => ['required', 'uuid', 'exists:trading_accounts,id'],
            'symbol' => ['required', 'string', 'max:40'],
            'timeframe' => ['required', Rule::in(self::TIMEFRAMES)],
            'start' => ['required', 'date'],
            'end' => ['required', 'date', 'after:start'],
        ]);
        $this->authorize('view', TradingAccount::query()->findOrFail($data['account_id']));
        $result = $this->engine->post('/internal/datasets/download', $data, 600);
        $this->audit->record('data.downloaded', actor: $request->user(), targetType: 'dataset', targetId: $result['id'], details: $data);

        return response()->json(Dataset::query()->findOrFail($result['id']), 201);
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
