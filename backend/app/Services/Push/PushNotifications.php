<?php

namespace App\Services\Push;

use App\Enums\UserRole;
use App\Jobs\SendPushNotification;
use App\Models\AppNotification;
use App\Models\MobileDevice;
use App\Models\User;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Log;
use Throwable;

/**
 * Queues a phone push for an in-app notification, at most once per
 * notification (a cache claim), whichever path saw it first:
 *  - Notifier (notifications written by Laravel) queues it immediately;
 *  - `tp:push-notifications` (every 15 s) picks up the ones the trading
 *    engine writes straight into the table (positions, risk, broker…).
 *
 * Recipients are the notification's user's devices; a platform notification
 * (user_id NULL: platform halt, engine offline) goes to active admins, who
 * are the ones who see it in the app. Queuing never throws: a push problem
 * must never break the notification itself.
 */
class PushNotifications
{
    private const CLAIM_SECONDS = 3600;

    public function __construct(private readonly FcmClient $fcm) {}

    public function enabled(): bool
    {
        return $this->fcm->configured();
    }

    public function queue(AppNotification $notification): void
    {
        try {
            if (! $this->enabled() || ! $this->wanted((string) $notification->type)
                || ! $this->recipientDevices($notification->user_id)->exists()) {
                return;
            }
            if (! Cache::add("push:claim:{$notification->id}", true, self::CLAIM_SECONDS)) {
                return; // already queued
            }
            SendPushNotification::dispatch($notification->id)->afterCommit();
        } catch (Throwable $e) {
            Log::warning('Could not queue a push notification', ['notification_id' => $notification->id, 'error' => $e->getMessage()]);
        }
    }

    /**
     * Routine, high-frequency types (every signal, every order sent) stay in the
     * app's notification list but don't buzz the phone. Configurable.
     */
    public function wanted(string $type): bool
    {
        return ! in_array($type, (array) config('tradepilot.push.skip_types', []), true);
    }

    /**
     * Devices that may receive a notification for $userId (NULL = platform
     * notification → active admins). Never another user's devices.
     *
     * @return Builder<MobileDevice>
     */
    public function recipientDevices(?string $userId): Builder
    {
        $query = MobileDevice::query();
        if ($userId !== null) {
            return $query->where('user_id', $userId)
                ->whereIn('user_id', User::query()->where('is_active', true)->select('id'));
        }

        return $query->whereIn('user_id', User::query()->where('is_active', true)->where('role', UserRole::Admin)->select('id'));
    }
}
