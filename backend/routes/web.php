<?php

use App\Http\Controllers\Api\BrokerController;
use Illuminate\Support\Facades\Route;

// The user interface is the Next.js dashboard (frontend/). Laravel serves the API only.
Route::get('/', fn () => response()->json([
    'app' => config('app.name'),
    'api' => url('/api'),
    'dashboard' => config('tradepilot.frontend_url'),
]));

// Deriv sends the browser back here after "Sign in with Deriv". It is a top-level
// navigation from auth.deriv.com, so its Referer is Deriv's: Sanctum would not treat
// it as a dashboard request and would ignore the session cookie (401). The web group
// always reads the session (the SameSite=lax cookie is sent on this GET navigation);
// the controller sends signed-out or disabled users back to the dashboard.
Route::get('api/brokers/deriv/oauth/callback', [BrokerController::class, 'derivOAuthCallback']);
