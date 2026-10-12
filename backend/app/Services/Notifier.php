<?php

namespace App\Services;

use App\Models\AppNotification;
use App\Services\Audit\Masker;
use App\Services\Push\PushNotifications;

/**
 * Creates in-app notifications from Laravel (the engine writes its own).
 * Types match trading-engine/src/fxrobot/notifications/types.py.
 *
 * Every notification has a recipient: a user id, or NULL for a platform
 * notification shown to admins (engine offline, platform halt).
 *
 * Each one is also queued as a phone push for the recipient's registered
 * devices (PushNotifications; a no-op until FCM is configured). A push
 * problem never breaks the notification itself.
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
        'strategy.entries_disabled' => ['critical', 'Strategy stopped by an administrator'],
        'strategy.entries_enabled' => ['info', 'Strategy allowed to trade again'],
        'system.engine_offline' => ['critical', 'Trading engine offline'],
        'system.engine_online' => ['success', 'Trading engine running'],
        'security.mfa' => ['info', 'Two-factor authentication'],
        'security.password' => ['info', 'Password changed'],
        'user.pending_approval' => ['info', 'New sign-up waiting for approval'],
        'user.approved' => ['success', 'Account approved'],
        'trading.live_revoked' => ['warning', 'Real-money trading turned off'],
        'report.daily' => ['info', 'Daily summary'],
        'backtest.failed' => ['warning', 'Backtest failed'],
    ];

    public function __construct(private readonly PushNotifications $push) {}

    public function notify(string $type, string $message, ?string $userId, ?string $accountId = null, array $data = []): AppNotification
    {
        [$severity, $title] = self::TYPES[$type] ?? ['info', $type];

        $notification = AppNotification::query()->create([
            'user_id' => $userId,
            'type' => $type,
            'severity' => $severity,
            'title' => $title,
            'message' => mb_substr($message, 0, 1000),
            'account_id' => $accountId,
            'data' => Masker::mask($data),
        ]);
        $this->push->queue($notification);

        return $notification;
    }
}
