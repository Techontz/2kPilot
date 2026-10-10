<?php

/*
| 2kPilot settings. Everything safety-relevant defaults to the safe value.
*/

return [

    // Hard lock. While false no LIVE (real-money) account can ever trade, and
    // no user can switch to LIVE mode.
    'live_trading_enabled' => (bool) env('LIVE_TRADING_ENABLED', false),

    // Typed phrase required (together with the password) to enter LIVE mode.
    'live_confirmation_phrase' => 'ENABLE LIVE TRADING',

    // Failed-login budget per email in 15 minutes (brute-force protection).
    'login_attempts' => (int) env('TP_LOGIN_ATTEMPTS', 5),
    // A looser cap per client IP across all emails (many users may share one IP).
    'login_attempts_per_ip' => (int) env('TP_LOGIN_ATTEMPTS_PER_IP', 50),

    // Public sign-up (POST /api/auth/register). Users can also be created with
    // `php artisan tp:user`.
    'registration_enabled' => (bool) env('TP_REGISTRATION_ENABLED', true),

    'frontend_url' => env('FRONTEND_URL', 'http://localhost:3421'),

    // AES-256-GCM key for broker secrets, shared with the trading engine.
    'broker_credentials_key' => env('BROKER_CREDENTIALS_KEY'),

    'engine' => [
        'url' => rtrim((string) env('ENGINE_URL', 'http://127.0.0.1:8431'), '/'),
        'secret' => env('ENGINE_API_SECRET'),
        'timeout' => (int) env('ENGINE_TIMEOUT_SECONDS', 30),
        // The engine is "offline" if it has not written a heartbeat for this long.
        'heartbeat_freshness_seconds' => 30,
        // Plain-English drafting waits for the AI (the engine allows 60 s per call, one repair round).
        'draft_timeout' => (int) env('ENGINE_DRAFT_TIMEOUT_SECONDS', 300),
    ],

    // Requests per user per minute: the dashboard API, and live-update stream (re)connections.
    'rate_limits' => [
        'api_per_minute' => (int) env('TP_API_PER_MINUTE', 300),
        'stream_per_minute' => (int) env('TP_STREAM_PER_MINUTE', 60),
    ],

    // Plain-English strategy drafts per user per hour (each one is a paid AI request).
    'ai_drafts_per_hour' => (int) env('AI_DRAFTS_PER_HOUR', 10),

    'deriv' => [
        'app_id' => env('DERIV_APP_ID'),
        'oauth_redirect_url' => env('DERIV_OAUTH_REDIRECT_URL'),
    ],

    // Live updates (GET /api/stream, Server-Sent Events). Each open dashboard
    // tab holds one PHP worker for up to max_seconds, then reconnects.
    'stream' => [
        'max_seconds' => (int) env('TP_STREAM_MAX_SECONDS', 55),
        'interval_seconds' => (float) env('TP_STREAM_INTERVAL_SECONDS', 2),
        'heartbeat_seconds' => (int) env('TP_STREAM_HEARTBEAT_SECONDS', 15),
    ],

    'mfa' => [
        // When true, every user must enrol before using the dashboard.
        // MFA is always mandatory for LIVE mode, whatever this says.
        'required' => (bool) env('TP_REQUIRE_MFA', false),
        'issuer' => env('APP_NAME', '2kPilot'),
        'recovery_codes' => 8,
    ],
];
