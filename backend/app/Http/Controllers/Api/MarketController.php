<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\BrokerSymbol;
use App\Models\TradingAccount;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Carbon;
use Illuminate\Validation\Rule;

/**
 * Markets: instruments reported by connected brokers, with live prices.
 * Prices come from the broker through the engine; PAPER prices are labelled.
 */
class MarketController extends Controller
{
    /** Brokers add and suspend markets; a list older than this is fetched again. */
    private const SYMBOLS_MAX_AGE_HOURS = 12;

    public function __construct(private readonly EngineClient $engine) {}

    public function instruments(Request $request): JsonResponse
    {
        $data = $request->validate([
            'account_id' => ['required', 'uuid'],
            'category' => ['nullable', 'string', 'max:30'],
            'refresh' => ['nullable', 'boolean'],
        ]);
        $account = TradingAccount::query()->with('connection')->findOrFail($data['account_id']);
        $this->authorize('use', $account); // asks the broker: the owner only
        $stored = fn () => BrokerSymbol::query()->where('connection_id', $account->connection_id)
            ->when($data['category'] ?? null, fn ($q, $c) => $q->where('category', $c))
            ->orderBy('category')->orderBy('canonical')->get();
        $symbols = $stored();
        $syncedAt = BrokerSymbol::query()->where('connection_id', $account->connection_id)->max('updated_at');
        $stale = $syncedAt === null || now()->subHours(self::SYMBOLS_MAX_AGE_HOURS)->greaterThan($syncedAt);
        $syncError = null;
        // Never synced, out of date, or asked for: ask the broker now. A failure
        // keeps the last list and says why, so an empty list is never silent.
        if ($symbols->isEmpty() || $stale || $request->boolean('refresh')) {
            try {
                $this->engine->get("/internal/accounts/{$account->id}/symbols");
                $symbols = $stored();
                $syncedAt = BrokerSymbol::query()->where('connection_id', $account->connection_id)->max('updated_at');
            } catch (EngineException $exception) {
                $syncError = $exception->getMessage();
            }
        }

        return response()->json([
            'account' => ['id' => $account->id, 'label' => $account->label, 'environment' => $account->environment->value],
            'provider' => config("brokers.{$account->connection->connector_type->value}.name"),
            'connection_status' => $account->connection->status->value,
            'simulated' => $account->isPaper(),
            'synced_at' => $syncedAt === null ? null : Carbon::parse($syncedAt)->toIso8601String(),
            'sync_error' => $syncError,
            'categories' => $symbols->countBy('category'),
            'instruments' => $symbols->map(fn (BrokerSymbol $s) => [
                'name' => $s->name,
                'canonical' => $s->canonical,
                'description' => $s->description,
                'category' => $s->category,
                'digits' => $s->digits,
                'trade_allowed' => $s->trade_allowed,
                'market_open' => $s->market_open,
            ])->values(),
        ]);
    }

    public function quotes(Request $request): JsonResponse
    {
        $data = $request->validate([
            'account_id' => ['required', 'uuid'],
            'symbols' => ['required', 'string', 'max:2000'],
        ]);
        $account = TradingAccount::query()->findOrFail($data['account_id']);
        $this->authorize('use', $account); // asks the broker: the owner only

        return response()->json($this->engine->get("/internal/accounts/{$account->id}/quotes", ['symbols' => $data['symbols']]));
    }

    public function instrument(Request $request, string $symbol): JsonResponse
    {
        $data = $request->validate([
            'account_id' => ['required', 'uuid'],
            'timeframe' => ['nullable', Rule::in(['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'])],
        ]);
        $account = TradingAccount::query()->with('connection')->findOrFail($data['account_id']);
        $this->authorize('use', $account); // asks the broker: the owner only
        $timeframe = $data['timeframe'] ?? 'H1';

        return response()->json([
            'symbol' => $this->engine->get("/internal/accounts/{$account->id}/symbols/".rawurlencode($symbol)),
            'quote' => $this->engine->get("/internal/accounts/{$account->id}/quotes", ['symbols' => $symbol])['quotes'][$symbol] ?? null,
            'candles' => $this->engine->get("/internal/accounts/{$account->id}/candles", ['symbol' => $symbol, 'timeframe' => $timeframe, 'count' => 200])['candles'],
            'timeframe' => $timeframe,
            'provider' => config("brokers.{$account->connection->connector_type->value}.name"),
            'simulated' => $account->isPaper(),
        ]);
    }

    /**
     * Which contracts the broker offers on a symbol (families, durations,
     * multipliers) and the default the dashboard should preselect.
     */
    public function contracts(Request $request): JsonResponse
    {
        $data = $request->validate(['account_id' => ['required', 'uuid'], 'symbol' => ['required', 'string', 'max:40']]);
        $account = TradingAccount::query()->ownedBy($request->user())->with('connection')->findOrFail($data['account_id']);
        $this->authorize('use', $account); // asks the broker: the owner only
        $offer = $this->engine->get("/internal/accounts/{$account->id}/contracts", ['symbol' => $data['symbol']]);

        return response()->json([
            'account' => ['id' => $account->id, 'label' => $account->label, 'environment' => $account->environment->value],
            'provider' => config("brokers.{$account->connection->connector_type->value}.name"),
        ] + $offer);
    }

    public function session(): JsonResponse
    {
        try {
            return response()->json($this->engine->get('/internal/market/session'));
        } catch (EngineException) {
            return response()->json(['now' => now()->toIso8601String(), 'session' => null, 'fx_open' => null]);
        }
    }
}
