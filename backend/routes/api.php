<?php

use App\Http\Controllers\Api\AccountController;
use App\Http\Controllers\Api\AnalyticsController;
use App\Http\Controllers\Api\AuditController;
use App\Http\Controllers\Api\AuthController;
use App\Http\Controllers\Api\BacktestController;
use App\Http\Controllers\Api\BrokerController;
use App\Http\Controllers\Api\DatasetController;
use App\Http\Controllers\Api\MarketController;
use App\Http\Controllers\Api\MfaController;
use App\Http\Controllers\Api\NotificationController;
use App\Http\Controllers\Api\OverviewController;
use App\Http\Controllers\Api\PositionController;
use App\Http\Controllers\Api\RecordsController;
use App\Http\Controllers\Api\RiskController;
use App\Http\Controllers\Api\StrategyController;
use App\Http\Controllers\Api\SystemController;
use App\Http\Controllers\Api\TradeController;
use App\Http\Controllers\Api\TradingController;
use Illuminate\Support\Facades\Route;

/*
| 2kFX REST API — consumed by the Next.js dashboard through same-origin
| cookie sessions (Sanctum SPA). Every route below "auth:sanctum" needs a
| logged-in, active user; writes are further checked by policies (owner only).
*/

Route::prefix('auth')->group(function () {
    Route::post('login', [AuthController::class, 'login'])->middleware('throttle:login');
    Route::post('mfa', [AuthController::class, 'challenge'])->middleware('throttle:mfa');
    Route::post('logout', [AuthController::class, 'logout'])->middleware('auth:sanctum');
});

// Deriv sends the browser back here after "Sign in with Deriv".
Route::get('brokers/deriv/oauth/callback', [BrokerController::class, 'derivOAuthCallback'])
    ->middleware(['auth:sanctum', 'active']);

Route::middleware(['auth:sanctum', 'active', 'throttle:api'])->group(function () {
    Route::get('auth/me', [AuthController::class, 'me']);

    // Settings → Security (always reachable, even when MFA enrolment is required)
    Route::prefix('auth/mfa')->middleware('throttle:mfa')->group(function () {
        Route::post('setup', [MfaController::class, 'setup']);
        Route::post('confirm', [MfaController::class, 'confirm']);
        Route::post('disable', [MfaController::class, 'disable']);
        Route::post('recovery-codes', [MfaController::class, 'recoveryCodes']);
    });

    Route::middleware('mfa.enrolled')->group(function () {
        Route::get('system/status', [SystemController::class, 'status']);
        Route::get('overview', [OverviewController::class, 'show']);

        // Global controls: STOP TRADING is always one click away.
        Route::get('trading/status', [TradingController::class, 'status']);
        Route::post('trading/stop', [TradingController::class, 'stop']);
        Route::post('trading/resume', [TradingController::class, 'resume']);
        Route::put('trading/mode', [TradingController::class, 'mode']);
        Route::post('trading/close-positions', [TradingController::class, 'closePositions'])->middleware('throttle:trading');

        // Broker Center
        Route::get('brokers/connectors', [BrokerController::class, 'connectors']);
        Route::get('brokers', [BrokerController::class, 'index']);
        Route::middleware('throttle:broker')->group(function () {
            Route::post('brokers/test', [BrokerController::class, 'test']);
            Route::post('brokers', [BrokerController::class, 'store']);
            Route::post('brokers/deriv/accounts', [BrokerController::class, 'derivAccounts']);
            Route::post('brokers/deriv/oauth/start', [BrokerController::class, 'derivOAuthStart']);
            Route::post('brokers/{connection}/reconnect', [BrokerController::class, 'reconnect']);
        });
        Route::post('brokers/{connection}/disconnect', [BrokerController::class, 'disconnect']);
        Route::delete('brokers/{connection}', [BrokerController::class, 'destroy']);

        Route::get('accounts', [AccountController::class, 'index']);
        Route::get('accounts/{account}', [AccountController::class, 'show']);
        Route::patch('accounts/{account}', [AccountController::class, 'update']);
        Route::post('accounts/{account}/sync', [AccountController::class, 'sync']);

        // Markets
        Route::get('markets/instruments', [MarketController::class, 'instruments']);
        Route::get('markets/quotes', [MarketController::class, 'quotes']);
        Route::get('markets/session', [MarketController::class, 'session']);
        Route::get('markets/instruments/{symbol}', [MarketController::class, 'instrument']);

        // Trade (manual tickets always pass the risk engine)
        Route::middleware('throttle:trading')->group(function () {
            Route::post('trade/preview', [TradeController::class, 'preview']);
            Route::post('trade/orders', [TradeController::class, 'submit']);
            Route::post('positions/{trade}/close', [PositionController::class, 'close']);
            Route::put('positions/{trade}', [PositionController::class, 'update']);
        });
        Route::get('positions', [PositionController::class, 'index']);
        Route::get('orders', [RecordsController::class, 'orders']);
        Route::get('history', [RecordsController::class, 'history']);
        Route::get('trades/{trade}', [RecordsController::class, 'trade']);
        Route::get('journal', [RecordsController::class, 'journal']);
        Route::get('signals', [RecordsController::class, 'signals']);

        // Strategies
        Route::get('strategies', [StrategyController::class, 'index']);
        Route::post('strategies/{strategy}/versions', [StrategyController::class, 'storeVersion']);
        Route::post('assignments', [StrategyController::class, 'assign']);
        Route::post('assignments/{assignment}/enable', [StrategyController::class, 'enable']);
        Route::post('assignments/{assignment}/pause', [StrategyController::class, 'pause']);
        Route::put('assignments/{assignment}/version', [StrategyController::class, 'switchVersion']);
        Route::delete('assignments/{assignment}', [StrategyController::class, 'unassign']);
        Route::get('assignments/{assignment}/evaluations', [StrategyController::class, 'evaluations']);

        // Backtesting & data
        Route::get('backtests', [BacktestController::class, 'index']);
        Route::post('backtests', [BacktestController::class, 'store']);
        Route::get('backtests/{backtest}', [BacktestController::class, 'show']);
        Route::get('backtests/{backtest}/trades', [BacktestController::class, 'trades']);
        Route::delete('backtests/{backtest}', [BacktestController::class, 'destroy']);
        Route::get('datasets', [DatasetController::class, 'index']);
        Route::post('datasets/synthetic', [DatasetController::class, 'synthetic']);
        Route::post('datasets/import', [DatasetController::class, 'import']);
        Route::post('datasets/download', [DatasetController::class, 'download']);
        Route::delete('datasets/{dataset}', [DatasetController::class, 'destroy']);

        // Risk
        Route::get('risk/profiles', [RiskController::class, 'index']);
        Route::post('risk/profiles', [RiskController::class, 'store']);
        Route::put('risk/profiles/{profile}', [RiskController::class, 'update']);
        Route::delete('risk/profiles/{profile}', [RiskController::class, 'destroy']);
        Route::get('risk/usage/{account}', [RiskController::class, 'usage']);

        // Analytics, notifications, audit
        Route::get('analytics/performance', [AnalyticsController::class, 'performance']);
        Route::get('notifications', [NotificationController::class, 'index']);
        Route::get('notifications/unread-count', [NotificationController::class, 'unreadCount']);
        Route::post('notifications/read', [NotificationController::class, 'markRead']);
        Route::get('audit', [AuditController::class, 'index']);
    });
});
