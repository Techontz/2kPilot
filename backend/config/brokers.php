<?php

/*
| Broker catalogue shown in Brokers → Add Broker.
|
| A connector is listed as "available" only when its adapter exists in the
| trading engine. Whether a specific account really works is proven by the
| connection test — nothing is ever shown as CONNECTED without one.
*/

return [
    'paper' => [
        'name' => 'Paper Trading',
        'tagline' => 'Built-in simulator. No broker, no real money.',
        'description' => 'Learn and test 2kFX safely. Uses SYNTHETIC prices (or replays a stored dataset). Every order and result is labelled PAPER.',
        'environments' => ['PAPER'],
        'auth_methods' => ['none'],
        'fields' => [
            ['name' => 'price_source', 'label' => 'Price source', 'kind' => 'select', 'default' => 'synthetic', 'options' => ['synthetic', 'replay'], 'help' => 'Synthetic = generated prices for testing. Replay = a stored dataset.'],
            ['name' => 'symbols', 'label' => 'Symbols', 'kind' => 'text', 'default' => 'EURUSD,GBPUSD,USDJPY', 'help' => 'Comma-separated. Synthetic supports EURUSD, GBPUSD, USDJPY, AUDUSD, USDCHF, USDCAD.'],
            ['name' => 'initial_balance', 'label' => 'Starting balance (USD)', 'kind' => 'number', 'default' => '10000'],
            ['name' => 'leverage', 'label' => 'Leverage', 'kind' => 'number', 'default' => '100'],
            ['name' => 'seconds_per_bar', 'label' => 'Simulation speed (seconds per 15-minute bar)', 'kind' => 'number', 'default' => '2', 'help' => 'Lower is faster (0 pauses it). The simulation never runs ahead of real time.'],
            ['name' => 'start_days_ago', 'label' => 'Start the simulation this many days ago', 'kind' => 'number', 'default' => '30', 'required' => false, 'help' => '0 = start today, so simulated prices follow the real clock.'],
        ],
    ],

    'deriv' => [
        'name' => 'Deriv',
        'tagline' => 'Real broker API — forex, synthetic indices, commodities and more.',
        'description' => 'Connects to the official Deriv API (developers.deriv.com). Trades are Deriv multiplier contracts with stop loss and take profit. Requires a Deriv App ID (DERIV_APP_ID).',
        'environments' => ['DEMO', 'LIVE'],
        'auth_methods' => ['pat', 'oauth'],
        'fields' => [
            ['name' => 'token', 'label' => 'Deriv personal access token', 'kind' => 'password', 'secret' => true, 'help' => 'Create one in your Deriv account with the "trade" scope. Stored encrypted; never shown again.'],
        ],
    ],

    'mt5_bridge' => [
        'name' => 'MetaTrader 5',
        'tagline' => 'Any MT5 broker, through the 2kFX Windows bridge.',
        'description' => 'Requires the 2kFX MT5 Bridge running on a Windows PC or VPS next to a logged-in MetaTrader 5 terminal. See docs/MT5_BRIDGE_SETUP.md.',
        'environments' => ['DEMO', 'LIVE'],
        'auth_methods' => ['credentials'],
        'fields' => [
            ['name' => 'bridge_url', 'label' => 'Bridge URL', 'kind' => 'url', 'help' => 'e.g. https://10.0.0.5:8710 (use HTTPS or a private tunnel).'],
            ['name' => 'bridge_secret', 'label' => 'Bridge secret', 'kind' => 'password', 'secret' => true, 'help' => 'The BRIDGE_SECRET configured on the bridge (32+ characters).'],
            ['name' => 'login', 'label' => 'MT5 account number', 'kind' => 'text'],
            ['name' => 'password', 'label' => 'MT5 password', 'kind' => 'password', 'secret' => true, 'help' => 'Stored encrypted; never shown again.'],
            ['name' => 'server', 'label' => 'MT5 server', 'kind' => 'text', 'help' => 'Exactly as shown in MT5, e.g. "ICMarketsSC-Demo".'],
            ['name' => 'verify_tls', 'label' => 'Verify TLS certificate', 'kind' => 'boolean', 'default' => 'true', 'required' => false],
        ],
    ],
];
