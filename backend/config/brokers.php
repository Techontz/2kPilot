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
        'description' => 'Learn and test 2kPilot safely. Uses SYNTHETIC prices (or replays a stored dataset). Every order and result is labelled PAPER.',
        'environments' => ['PAPER'],
        'auth_methods' => ['none'],
        'fields' => [
            ['name' => 'price_source', 'label' => 'Price source', 'kind' => 'select', 'default' => 'synthetic', 'options' => ['synthetic', 'replay'], 'help' => 'Synthetic = generated prices for testing. Replay = a stored dataset.'],
            ['name' => 'symbols', 'label' => 'Symbols', 'kind' => 'text', 'default' => 'EURUSD,GBPUSD,USDJPY', 'help' => 'Comma-separated. Synthetic supports EURUSD, GBPUSD, USDJPY, AUDUSD, USDCHF, USDCAD.'],
            ['name' => 'initial_balance', 'label' => 'Starting balance (USD)', 'kind' => 'number', 'default' => '10000'],
            ['name' => 'leverage', 'label' => 'Leverage', 'kind' => 'number', 'default' => '100'],
            ['name' => 'seconds_per_bar', 'label' => 'Simulation speed (seconds per 15 simulated minutes)', 'kind' => 'number', 'default' => '2', 'help' => 'Lower is faster (0 pauses it). It slows down to one candle of your strategy per update (e.g. 5 minutes for M5) so no candle is skipped, and never runs ahead of real time.'],
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
];
