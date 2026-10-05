<?php

namespace App\Services;

use App\Models\AppNotification;
use App\Services\Audit\Masker;

/**
 * Creates in-app notifications from Laravel (the engine writes its own).
 * Types match trading-engine/src/fxrobot/notifications/types.py.
 */
class Notifier
{
    private const TYPES = [
        'broker.connected' => ['success', 'Broker connected'],
        'broker.disconnected' => ['warning', 'Broker disconnected'],
        'broker.error' => ['critical', 'Broker error'],
        'trading.stopped' => ['warning', 'Trading stopped'],
        'trading.resumed' => ['info', 'Trading resumed'],
        'trading.emergency_stop' => ['critical', 'Emergency stop'],
        'strategy.paused' => ['warning', 'Strategy paused'],
        'system.engine_offline' => ['critical', 'Trading engine offline'],
        'system.engine_online' => ['success', 'Trading engine running'],
        'security.mfa' => ['info', 'Two-factor authentication'],
        'report.daily' => ['info', 'Daily summary'],
        'backtest.failed' => ['warning', 'Backtest failed'],
    ];

    public function notify(string $type, string $message, ?string $accountId = null, array $data = []): AppNotification
    {
        [$severity, $title] = self::TYPES[$type] ?? ['info', $type];

        return AppNotification::query()->create([
            'type' => $type,
            'severity' => $severity,
            'title' => $title,
            'message' => mb_substr($message, 0, 1000),
            'account_id' => $accountId,
            'data' => Masker::mask($data),
        ]);
    }
}
