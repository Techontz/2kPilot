<?php

namespace App\Services;

use App\Models\AppNotification;
use App\Services\Audit\Masker;

/**
 * Creates in-app notifications from Laravel (the engine writes its own).
 * Types match trading-engine/src/fxrobot/notifications/types.py.
 *
 * Every notification has a recipient: a user id, or NULL for a platform
 * notification shown to admins (engine offline, platform halt).
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
        'platform.halted' => ['critical', 'Platform halted'],
        'platform.resumed' => ['info', 'Platform halt lifted'],
        'strategy.paused' => ['warning', 'Strategy paused'],
        'system.engine_offline' => ['critical', 'Trading engine offline'],
        'system.engine_online' => ['success', 'Trading engine running'],
        'security.mfa' => ['info', 'Two-factor authentication'],
        'security.password' => ['info', 'Password changed'],
        'report.daily' => ['info', 'Daily summary'],
        'backtest.failed' => ['warning', 'Backtest failed'],
    ];

    public function notify(string $type, string $message, ?string $userId, ?string $accountId = null, array $data = []): AppNotification
    {
        [$severity, $title] = self::TYPES[$type] ?? ['info', $type];

        return AppNotification::query()->create([
            'user_id' => $userId,
            'type' => $type,
            'severity' => $severity,
            'title' => $title,
            'message' => mb_substr($message, 0, 1000),
            'account_id' => $accountId,
            'data' => Masker::mask($data),
        ]);
    }
}
