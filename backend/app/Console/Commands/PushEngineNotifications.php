<?php

namespace App\Console\Commands;

use App\Models\AppNotification;
use App\Models\MobileDevice;
use App\Services\Push\PushNotifications;
use Illuminate\Console\Command;

/**
 * Scheduled every 15 seconds. The trading engine writes its notifications
 * (position opened/closed, stop loss, risk limit, broker errors…) straight
 * into the `notifications` table, so Laravel's Notifier never sees them.
 * This queues a phone push for each recent one whose recipient has a
 * registered device. Notifications already queued by the Notifier are
 * skipped (PushNotifications claims each id once). No-op while push is off.
 */
class PushEngineNotifications extends Command
{
    protected $signature = 'tp:push-notifications {--minutes=2 : How far back to look}';

    protected $description = 'Queue phone pushes for new notifications (including those written by the trading engine)';

    public function handle(PushNotifications $push): int
    {
        if (! $push->enabled()) {
            return self::SUCCESS;
        }
        $since = now()->subMinutes(max(1, (int) $this->option('minutes')));
        AppNotification::query()
            ->where(fn ($q) => $q->whereIn('user_id', MobileDevice::query()->select('user_id'))->orWhereNull('user_id'))
            ->where('created_at', '>=', $since)
            ->orderBy('id')
            ->limit(1000)
            ->get()
            ->each(fn (AppNotification $notification) => $push->queue($notification));

        return self::SUCCESS;
    }
}
