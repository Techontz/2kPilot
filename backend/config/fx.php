<?php

/*
| 2kFX ROBOT settings. Everything safety-relevant defaults to the safe value.
*/

return [

    // Hard lock. While false no LIVE (real-money) account can ever trade, and
    // the operating mode cannot be switched to LIVE.
    'live_trading_enabled' => (bool) env('LIVE_TRADING_ENABLED', false),

    // Typed phrase required (together with the password) to enter LIVE mode.
    'live_confirmation_phrase' => 'ENABLE LIVE TRADING',

    // Failed-login budget per email+IP in 15 minutes (brute-force protection).
    'login_attempts' => (int) env('FX_LOGIN_ATTEMPTS', 5),

    'frontend_url' => env('FRONTEND_URL', 'http://localhost:3421'),

    // AES-256-GCM key for broker secrets, shared with the trading engine.
    'broker_credentials_key' => env('BROKER_CREDENTIALS_KEY'),

    'engine' => [
        'url' => rtrim((string) env('ENGINE_URL', 'http://127.0.0.1:8431'), '/'),
        'secret' => env('ENGINE_API_SECRET'),
        'timeout' => (int) env('ENGINE_TIMEOUT_SECONDS', 30),
        // The engine is "offline" if it has not written a heartbeat for this long.
        'heartbeat_freshness_seconds' => 30,
    ],

    'deriv' => [
        'app_id' => env('DERIV_APP_ID'),
        'oauth_redirect_url' => env('DERIV_OAUTH_REDIRECT_URL'),
    ],

    'mfa' => [
        // When true, every user must enrol before using the dashboard.
        'required' => (bool) env('FX_REQUIRE_MFA', false),
        'issuer' => env('APP_NAME', '2kFX ROBOT'),
        'recovery_codes' => 8,
    ],
];
