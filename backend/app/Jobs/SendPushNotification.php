<?php

namespace App\Jobs;

use App\Models\AppNotification;
use App\Services\Push\FcmClient;
use App\Services\Push\PushNotifications;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;
use Illuminate\Support\Facades\Log;

/**
 * Sends one in-app notification to the recipient's phones through Firebase
 * Cloud Messaging (queue "notifications", Horizon's default supervisor).
 *
 * The payload is deliberately small: the notification's title and message,
 * plus ids the app needs to open the right screen (type, notification_id,
 * trade_id, account_id). Never secrets or broker data.
 *
 * Device tokens FCM reports as dead are deleted. Devices that were rate
 * limited (429) or hit an FCM outage are retried by a follow-up job for just
 * those devices, honouring Retry-After, up to 3 rounds — so a device never
 * gets the same notification twice.
 */
class SendPushNotification implements ShouldQueue
{
    use Queueable;

    public const MAX_ROUNDS = 3;

    public int $tries = 1;

    public int $timeout = 60;

    /** @param list<int>|null $deviceIds only these devices (a retry round); null = all recipients */
    public function __construct(
        public readonly int $notificationId,
        public readonly ?array $deviceIds = null,
        public readonly int $round = 1,
    ) {
        $this->onQueue('notifications');
    }

    public function handle(FcmClient $fcm, PushNotifications $push): void
    {
        if (! $fcm->configured()) {
            return;
        }
        $notification = AppNotification::query()->find($this->notificationId);
        if ($notification === null) {
            return;
        }
        $devices = $push->recipientDevices($notification->user_id)
            ->when($this->deviceIds !== null, fn ($q) => $q->whereIn('id', $this->deviceIds))
            ->get();
        $message = self::message($notification);
        $retry = [];
        $retryAfter = null;
        foreach ($devices as $device) {
            $result = $fcm->send($device->fcm_token, $message);
            if ($result === FcmClient::INVALID) {
                $device->delete();
            } elseif ($result === FcmClient::RETRY) {
                $retry[] = $device->id;
                $retryAfter = max($retryAfter ?? 0, $fcm->retryAfter ?? 0) ?: null;
            }
        }
        if ($retry !== [] && $this->round < self::MAX_ROUNDS) {
            self::dispatch($this->notificationId, $retry, $this->round + 1)
                ->delay(now()->addSeconds($retryAfter ?? 30 * $this->round));
        } elseif ($retry !== []) {
            Log::warning('Push notification not delivered after retries', ['notification_id' => $this->notificationId, 'devices' => count($retry)]);
        }
    }

    /** The FCM v1 message (without the device token). */
    public static function message(AppNotification $notification): array
    {
        $payload = (array) $notification->data;
        $data = array_filter([
            'type' => (string) $notification->type,
            'notification_id' => (string) $notification->id,
            'trade_id' => isset($payload['trade_id']) && is_scalar($payload['trade_id']) ? (string) $payload['trade_id'] : null,
            'account_id' => $notification->account_id !== null ? (string) $notification->account_id : null,
        ], fn ($value) => $value !== null && $value !== '');

        return [
            'notification' => [
                'title' => mb_substr((string) $notification->title, 0, 100),
                'body' => mb_substr((string) $notification->message, 0, 300),
            ],
            'data' => $data,
            'android' => [
                'priority' => 'high', // trading alerts are time-sensitive and always shown
                'notification' => ['channel_id' => 'trading'],
            ],
            'apns' => [
                'payload' => ['aps' => ['sound' => 'default']],
            ],
        ];
    }
}
