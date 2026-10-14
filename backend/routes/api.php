<?php

use App\Http\Controllers\Api\AccountController;
use App\Http\Controllers\Api\AdminController;
use App\Http\Controllers\Api\AnalyticsController;
use App\Http\Controllers\Api\AuditController;
use App\Http\Controllers\Api\AuthController;
use App\Http\Controllers\Api\BacktestController;
use App\Http\Controllers\Api\BrokerController;
use App\Http\Controllers\Api\DatasetController;
use App\Http\Controllers\Api\MarketController;
use App\Http\Controllers\Api\MfaController;
use App\Http\Controllers\Api\MobileAuthController;
use App\Http\Controllers\Api\MobileDeviceController;
use App\Http\Controllers\Api\NotificationController;
use App\Http\Controllers\Api\OverviewController;
use App\Http\Controllers\Api\PositionController;
use App\Http\Controllers\Api\RecordsController;
use App\Http\Controllers\Api\RiskController;
use App\Http\Controllers\Api\StrategyController;
use App\Http\Controllers\Api\StreamController;
use App\Http\Controllers\Api\SystemController;
use App\Http\Controllers\Api\TradeController;
use App\Http\Controllers\Api\TradingController;
use Illuminate\Support\Facades\Route;

/*
| 2kPilot REST API — consumed by the Next.js dashboard through same-origin
| cookie sessions (Sanctum SPA). Every route below "auth:sanctum" needs a
| logged-in, active user. Every user works on their OWN records only: indexes
| are scoped to the user, and policies check ownership of every bound record.
| Admin routes (platform halt) are gated by "operate-platform".
*/

Route::prefix('auth')->group(function () {
    Route::post('register', [AuthController::class, 'register'])->middleware('throttle:register');
    Route::post('login', [AuthController::class, 'login'])->middleware('throttle:login');
    Route::post('mfa', [AuthController::class, 'challenge'])->middleware('throttle:mfa');
    Route::post('logout', [AuthController::class, 'logout'])->middleware('auth:sanctum');
});

// Mobile app sign-in: bearer tokens instead of the cookie session (same "login"
// throttle and MFA lockout as the website).
Route::prefix('mobile/auth')->group(function () {
    Route::post('login', [MobileAuthController::class, 'login'])->middleware('throttle:login');
    Route::post('mfa', [MobileAuthController::class, 'challenge'])->middleware('throttle:mfa');
    Route::post('logout', [MobileAuthController::class, 'logout'])->middleware(['auth:sanctum', 'mobile.token']);
});

// The "Sign in with Deriv" return URL (GET api/brokers/deriv/oauth/callback) lives in
// routes/web.php: it is a full-page redirect from Deriv, not a dashboard API call.

// Live updates (Server-Sent Events). Outside "throttle:api": each open tab
// keeps one connection and reconnects about once a minute.
Route::get('stream', [StreamController::class, 'show'])
    ->middleware(['auth:sanctum', 'active', 'approved', 'mfa.enrolled', 'throttle:stream']);

// STOP TRADING and Close positions: outside "throttle:api" on their own
// generous per-user budget, so heavy polling can never block them. Stop does
// not wait for MFA enrolment either: stopping is always safe.
Route::middleware(['auth:sanctum', 'active', 'approved', 'throttle:trading-stop'])->group(function () {
    Route::post('trading/stop', [TradingController::class, 'stop']);
    Route::post('trading/close-positions', [TradingController::class, 'closePositions'])->middleware('mfa.enrolled');
});

// 'approved': a new sign-up only gets auth/me (the waiting page) until an admin approves.
Route::middleware(['auth:sanctum', 'active', 'approved', 'throttle:api'])->group(function () {
    Route::get('auth/me', [AuthController::class, 'me']);

    // Signed-in mobile devices (from the app or the website).
    Route::get('auth/tokens', [MobileAuthController::class, 'tokens']);
    Route::delete('auth/tokens/{id}', [MobileAuthController::class, 'revokeToken']);

    // Push notification registration (mobile app only).
    Route::middleware('mobile.token')->group(function () {
        Route::post('mobile/devices', [MobileDeviceController::class, 'store']);
        Route::delete('mobile/devices', [MobileDeviceController::class, 'destroy']);
    });

    // Settings → Security (always reachable, even when MFA enrolment is required;
    // website only: the mobile app cannot change the password or MFA).
    Route::prefix('auth/mfa')->middleware(['web.only', 'throttle:mfa'])->group(function () {
        Route::post('setup', [MfaController::class, 'setup']);
        Route::post('confirm', [MfaController::class, 'confirm']);
        Route::post('disable', [MfaController::class, 'disable']);
        Route::post('recovery-codes', [MfaController::class, 'recoveryCodes']);
    });

    Route::put('auth/password', [AuthController::class, 'changePassword'])->middleware(['web.only', 'throttle:password']);

    Route::middleware('mfa.enrolled')->group(function () {
        Route::get('system/status', [SystemController::class, 'status']);
        Route::get('overview', [OverviewController::class, 'show']);

        // The user's own controls (STOP TRADING and Close positions are above).
        Route::get('trading/status', [TradingController::class, 'status']);
        Route::post('trading/resume', [TradingController::class, 'resume']);
        Route::put('trading/mode', [TradingController::class, 'mode']);

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
        Route::get('markets/contracts', [MarketController::class, 'contracts']);
        Route::get('markets/candles', [MarketController::class, 'candles']);
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
        Route::get('history/export', [RecordsController::class, 'export']);
        Route::get('history', [RecordsController::class, 'history']);
        Route::get('trades/{trade}', [RecordsController::class, 'trade']);
        Route::get('journal', [RecordsController::class, 'journal']);
        Route::get('signals', [RecordsController::class, 'signals']);

        // Strategies
        Route::get('strategies', [StrategyController::class, 'index']);
        Route::get('strategies/catalog', [StrategyController::class, 'catalog']);
        Route::post('strategies', [StrategyController::class, 'store']);
        Route::post('strategies/import', [StrategyController::class, 'import']);
        Route::post('strategies/draft', [StrategyController::class, 'draft'])->middleware('throttle:strategy-draft');
        Route::patch('strategies/{strategy}', [StrategyController::class, 'update']);
        Route::delete('strategies/{strategy}', [StrategyController::class, 'destroy']);
        Route::get('strategies/{strategy}/export', [StrategyController::class, 'export']);
        Route::post('strategies/{strategy}/copy', [StrategyController::class, 'copy']);
        Route::post('strategies/{strategy}/versions', [StrategyController::class, 'storeVersion']);
        Route::post('strategies/{strategy}/activate', [StrategyController::class, 'activate'])->middleware('throttle:trading');
        Route::post('strategies/{strategy}/deactivate', [StrategyController::class, 'deactivate']);
        Route::post('assignments', [StrategyController::class, 'assign']);
        Route::post('assignments/{assignment}/enable', [StrategyController::class, 'enable']);
        Route::post('assignments/{assignment}/pause', [StrategyController::class, 'pause']);
        Route::put('assignments/{assignment}/version', [StrategyController::class, 'switchVersion']);
        Route::put('assignments/{assignment}/contract', [StrategyController::class, 'updateContract']);
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
        Route::post('datasets/download', [DatasetController::class, 'download'])->middleware('throttle:broker');
        Route::delete('datasets/{dataset}', [DatasetController::class, 'destroy']);

        // Risk
        Route::get('risk/profiles', [RiskController::class, 'index']);
        Route::post('risk/profiles', [RiskController::class, 'store']);
        Route::put('risk/profiles/{profile}', [RiskController::class, 'update']);
        Route::delete('risk/profiles/{profile}', [RiskController::class, 'destroy']);
        Route::get('risk/usage/{account}', [RiskController::class, 'usage']);

        // Analytics, notifications, audit
        Route::get('analytics/performance', [AnalyticsController::class, 'performance']);
        Route::get('analytics/scorecard', [AnalyticsController::class, 'scorecard']);
        Route::get('notifications', [NotificationController::class, 'index']);
        Route::get('notifications/unread-count', [NotificationController::class, 'unreadCount']);
        Route::post('notifications/read', [NotificationController::class, 'markRead']);
        Route::get('audit', [AuditController::class, 'index']);

        // Platform operations (admins only, website only)
        Route::prefix('admin')->middleware(['web.only', 'throttle:trading'])->group(function () {
            Route::post('halt', [AdminController::class, 'halt']);
            Route::post('resume', [AdminController::class, 'resume']);
            // Strategy emergency stop: blocks NEW entries from one strategy for everyone.
            Route::post('strategies/{strategy}/disable', [AdminController::class, 'disableStrategy']);
            Route::post('strategies/{strategy}/enable', [AdminController::class, 'enableStrategy']);
            // Users: approve new sign-ups, disable or re-enable accounts.
            Route::get('users', [AdminController::class, 'users']);
            Route::post('users/{user}/approve', [AdminController::class, 'approveUser']);
            Route::post('users/{user}/disable', [AdminController::class, 'disableUser']);
            Route::post('users/{user}/enable', [AdminController::class, 'enableUser']);
        });
    });
});
