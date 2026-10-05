<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use App\Services\Security\BrokerVault;
use App\Services\Trading\TradingControl;
use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\DB;

/** Settings → System: what is configured, and is everything healthy? */
class SystemController extends Controller
{
    public function __construct(
        private readonly TradingControl $control,
        private readonly EngineClient $engine,
        private readonly BrokerVault $vault,
    ) {}

    public function status(): JsonResponse
    {
        try {
            $engine = $this->engine->get('/internal/health');
        } catch (EngineException|\RuntimeException $e) {
            $engine = ['status' => 'unreachable', 'detail' => $e->getMessage()];
        }

        return response()->json([
            'app' => config('app.name'),
            'environment' => app()->environment(),
            'database' => DB::connection()->getDatabaseName() ? 'ok' : 'error',
            'trading' => $this->control->status()->toArray(),
            'engine' => $engine,
            'live_trading_enabled' => (bool) config('fx.live_trading_enabled'),
            'broker_vault_configured' => $this->vault->configured(),
            'deriv_app_id_configured' => (bool) config('fx.deriv.app_id'),
            'mfa_required' => (bool) config('fx.mfa.required'),
            'queue_connection' => config('queue.default'),
        ]);
    }
}
