<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\BrokerSymbol;
use App\Models\TradingAccount;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

/**
 * Markets: instruments reported by connected brokers, with live prices.
 * Prices come from the broker through the engine; PAPER prices are labelled.
 */
class MarketController extends Controller
{
    public function __construct(private readonly EngineClient $engine) {}

    public function instruments(Request $request): JsonResponse
    {
        $data = $request->validate(['account_id' => ['required', 'uuid'], 'category' => ['nullable', 'string', 'max:30']]);
        $account = TradingAccount::query()->with('connection')->findOrFail($data['account_id']);
        $this->authorize('view', $account);
        $symbols = BrokerSymbol::query()->where('connection_id', $account->connection_id)
            ->when($data['category'] ?? null, fn ($q, $c) => $q->where('category', $c))
            ->orderBy('category')->orderBy('canonical')->get();
        if ($symbols->isEmpty()) { // not synced yet: ask the broker now
            try {
                $this->engine->get("/internal/accounts/{$account->id}/symbols");
                $symbols = BrokerSymbol::query()->where('connection_id', $account->connection_id)->orderBy('category')->orderBy('canonical')->get();
            } catch (EngineException) {
                // shown as an empty state with the connection status
            }
        }

        return response()->json([
            'account' => ['id' => $account->id, 'label' => $account->label, 'environment' => $account->environment->value],
            'provider' => config("brokers.{$account->connection->connector_type->value}.name"),
            'connection_status' => $account->connection->status->value,
            'simulated' => $account->isPaper(),
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
        $this->authorize('view', $account);

        return response()->json($this->engine->get("/internal/accounts/{$account->id}/quotes", ['symbols' => $data['symbols']]));
    }

    public function instrument(Request $request, string $symbol): JsonResponse
    {
        $data = $request->validate([
            'account_id' => ['required', 'uuid'],
            'timeframe' => ['nullable', Rule::in(['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'])],
        ]);
        $account = TradingAccount::query()->with('connection')->findOrFail($data['account_id']);
        $this->authorize('view', $account);
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

    public function session(): JsonResponse
    {
        try {
            return response()->json($this->engine->get('/internal/market/session'));
        } catch (EngineException) {
            return response()->json(['now' => now()->toIso8601String(), 'session' => null, 'fx_open' => null]);
        }
    }
}
