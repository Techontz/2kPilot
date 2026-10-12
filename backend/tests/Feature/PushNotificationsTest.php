<?php

namespace Tests\Feature;

use App\Jobs\SendPushNotification;
use App\Models\AppNotification;
use App\Models\MobileDevice;
use App\Models\User;
use App\Services\Notifier;
use App\Services\Trading\TradingControl;
use Firebase\JWT\JWT;
use Firebase\JWT\Key;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Queue;
use Tests\TestCase;

/** Phone pushes through Firebase Cloud Messaging (HTTP v1). */
class PushNotificationsTest extends TestCase
{
    private const FCM = 'fcm.googleapis.com/v1/projects/tp-test/messages:send';

    private string $publicKey;

    private ?string $credentialsPath = null;

    protected function tearDown(): void
    {
        if ($this->credentialsPath !== null) {
            @unlink($this->credentialsPath);
        }
        parent::tearDown();
    }

    /** A throw-away service account, like the JSON key downloaded from Firebase. */
    private function configurePush(): void
    {
        $key = openssl_pkey_new(['private_key_bits' => 2048, 'private_key_type' => OPENSSL_KEYTYPE_RSA]);
        openssl_pkey_export($key, $private);
        $this->publicKey = openssl_pkey_get_details($key)['key'];
        $this->credentialsPath = tempnam(sys_get_temp_dir(), 'fcm');
        file_put_contents($this->credentialsPath, json_encode([
            'type' => 'service_account',
            'project_id' => 'tp-test',
            'private_key_id' => 'kid-1',
            'private_key' => $private,
            'client_email' => 'push@tp-test.iam.gserviceaccount.com',
            'token_uri' => 'https://oauth2.googleapis.com/token',
        ]));
        config(['tradepilot.push.project_id' => 'tp-test', 'tradepilot.push.credentials' => $this->credentialsPath]);
    }

    /** @param array<string, mixed> $fcm per device token: an Http response (default 200) */
    private function fakeGoogle(array $fcm = []): void
    {
        Http::fake([
            'oauth2.googleapis.com/token' => Http::response(['access_token' => 'ya29.test-token', 'expires_in' => 3599, 'token_type' => 'Bearer']),
            'fcm.googleapis.com/*' => function (Request $request) use ($fcm) {
                return $fcm[$request['message']['token']] ?? Http::response(['name' => 'projects/tp-test/messages/1']);
            },
        ]);
    }

    private function device(User $user, string $fcmToken, string $platform = 'android'): MobileDevice
    {
        return MobileDevice::query()->create([
            'user_id' => $user->id, 'fcm_token' => $fcmToken, 'fcm_token_hash' => MobileDevice::hashToken($fcmToken),
            'platform' => $platform, 'last_seen_at' => now(),
        ]);
    }

    /** @return list<string> the device tokens FCM was asked to deliver to */
    private function sentTo(): array
    {
        return Http::recorded(fn (Request $r) => str_contains($r->url(), 'fcm.googleapis.com'))
            ->map(fn ($pair) => $pair[0]['message']['token'])->values()->all();
    }

    public function test_without_configuration_push_is_a_silent_no_op(): void
    {
        Http::fake();
        Queue::fake();
        $this->device($this->me(), 'phone-1');
        $note = app(Notifier::class)->notify('trading.stopped', 'Stopped.', $this->me()->id);

        $this->assertDatabaseHas('notifications', ['id' => $note->id]);
        Queue::assertNothingPushed();
        app()->call([new SendPushNotification($note->id), 'handle']);
        $this->artisan('tp:push-notifications')->assertSuccessful();
        Http::assertNothingSent();
    }

    public function test_a_missing_credentials_file_also_means_off(): void
    {
        Queue::fake();
        config(['tradepilot.push.project_id' => 'tp-test', 'tradepilot.push.credentials' => '/nonexistent/fcm.json']);
        $this->device($this->me(), 'phone-1');
        app(Notifier::class)->notify('trading.stopped', 'Stopped.', $this->me()->id);
        Queue::assertNothingPushed();
    }

    public function test_the_notifier_queues_a_push_on_the_notifications_queue(): void
    {
        $this->configurePush();
        Queue::fake();
        $this->device($this->me(), 'phone-1');
        $note = app(Notifier::class)->notify('trading.stopped', 'Stopped.', $this->me()->id);

        Queue::assertPushedOn('notifications', SendPushNotification::class, fn (SendPushNotification $job) => $job->notificationId === $note->id);
        // A user without a registered phone: nothing to queue.
        app(Notifier::class)->notify('trading.stopped', 'Stopped.', $this->user()->id);
        Queue::assertPushed(SendPushNotification::class, 1);
    }

    public function test_routine_types_stay_in_app_without_a_phone_push(): void
    {
        $this->configurePush();
        Queue::fake();
        $this->device($this->me(), 'phone-1');
        app(Notifier::class)->notify('signal.generated', 'Signal.', $this->me()->id);
        app(Notifier::class)->notify('order.submitted', 'Order sent.', $this->me()->id);
        Queue::assertNothingPushed();

        app(Notifier::class)->notify('position.closed', 'Closed.', $this->me()->id);
        Queue::assertPushed(SendPushNotification::class, 1);
    }

    public function test_the_push_reaches_fcm_v1_with_a_service_account_token_and_a_small_payload(): void
    {
        $this->configurePush();
        $this->fakeGoogle();
        $this->device($this->me(), 'phone-1');
        $note = app(Notifier::class)->notify('trading.stopped', 'EURUSD stopped.', $this->me()->id,
            data: ['trade_id' => 'trade-123', 'api_token' => 'should-never-leave']);

        // OAuth2: a JWT bearer grant signed by the service account's key.
        Http::assertSent(function (Request $r) {
            if ($r->url() !== 'https://oauth2.googleapis.com/token') {
                return false;
            }
            $this->assertSame('urn:ietf:params:oauth:grant-type:jwt-bearer', $r['grant_type']);
            $claims = JWT::decode($r['assertion'], new Key($this->publicKey, 'RS256'));
            $this->assertSame('push@tp-test.iam.gserviceaccount.com', $claims->iss);
            $this->assertSame('https://www.googleapis.com/auth/firebase.messaging', $claims->scope);
            $this->assertSame('https://oauth2.googleapis.com/token', $claims->aud);
            $this->assertLessThanOrEqual(3600, $claims->exp - $claims->iat);

            return true;
        });
        // FCM v1: the message for this device.
        Http::assertSent(function (Request $r) use ($note) {
            if ($r->url() !== 'https://'.self::FCM) {
                return false;
            }
            $this->assertSame('Bearer ya29.test-token', $r->header('Authorization')[0]);
            $message = $r['message'];
            $this->assertSame('phone-1', $message['token']);
            $this->assertSame(['title' => 'Trading stopped', 'body' => 'EURUSD stopped.'], $message['notification']);
            $this->assertSame(['type' => 'trading.stopped', 'notification_id' => (string) $note->id, 'trade_id' => 'trade-123'], $message['data']);
            $this->assertSame('trading', $message['android']['notification']['channel_id']);
            $this->assertSame('default', $message['apns']['payload']['aps']['sound']);
            $this->assertStringNotContainsString('should-never-leave', json_encode($message));

            return true;
        });
    }

    public function test_the_payload_carries_the_account_id_and_bounded_text(): void
    {
        $note = (new AppNotification)->forceFill(['id' => 42, 'type' => 'position.opened', 'title' => 'Position opened',
            'message' => str_repeat('x', 1000), 'account_id' => 'acc-1', 'data' => ['trade_id' => 't-9', 'credentials' => ['k' => 'v']]]);
        $message = SendPushNotification::message($note);
        $this->assertSame(['type' => 'position.opened', 'notification_id' => '42', 'trade_id' => 't-9', 'account_id' => 'acc-1'], $message['data']);
        $this->assertSame(300, mb_strlen($message['notification']['body']));
        $this->assertSame(['notification', 'data', 'android', 'apns'], array_keys($message));
    }

    public function test_the_access_token_is_cached_between_pushes(): void
    {
        $this->configurePush();
        $this->fakeGoogle();
        $this->device($this->me(), 'phone-1');
        app(Notifier::class)->notify('trading.stopped', 'One.', $this->me()->id);
        app(Notifier::class)->notify('trading.resumed', 'Two.', $this->me()->id);

        $this->assertCount(1, Http::recorded(fn (Request $r) => str_contains($r->url(), 'oauth2.googleapis.com')));
        $this->assertSame(['phone-1', 'phone-1'], $this->sentTo());
    }

    public function test_only_the_recipients_own_devices_get_the_push(): void
    {
        $this->configurePush();
        $this->fakeGoogle();
        $me = $this->me();
        $other = $this->user();
        $this->device($me, 'my-phone');
        $this->device($me, 'my-ipad', 'ios');
        $this->device($other, 'their-phone');

        app(Notifier::class)->notify('trading.stopped', 'Stopped.', $me->id);
        $this->assertEqualsCanonicalizing(['my-phone', 'my-ipad'], $this->sentTo());
    }

    public function test_platform_notifications_go_to_active_admins_only(): void
    {
        $this->configurePush();
        $this->fakeGoogle();
        $admin = $this->admin();
        $this->device($admin, 'admin-phone');
        $this->device($this->me(), 'user-phone');

        app(TradingControl::class)->haltPlatform($admin, 'exchange outage');
        $this->assertSame(['admin-phone'], $this->sentTo());
    }

    public function test_stopping_trading_pushes_the_users_own_notification(): void
    {
        $this->configurePush();
        $this->fakeGoogle();
        $this->device($this->me(), 'my-phone');
        app(TradingControl::class)->resume($this->me());
        app(TradingControl::class)->stop($this->me(), 'from the dashboard');

        $types = Http::recorded(fn (Request $r) => str_contains($r->url(), 'fcm.googleapis.com'))->map(fn ($p) => $p[0]['message']['data']['type'])->values()->all();
        $this->assertSame(['trading.resumed', 'trading.stopped'], $types);
    }

    public function test_dead_device_tokens_are_removed(): void
    {
        $this->configurePush();
        $this->fakeGoogle([
            'gone' => Http::response(['error' => ['code' => 404, 'status' => 'NOT_FOUND', 'details' => [['@type' => 'type.googleapis.com/google.firebase.fcm.v1.FcmError', 'errorCode' => 'UNREGISTERED']]]], 404),
            'garbage' => Http::response(['error' => ['code' => 400, 'status' => 'INVALID_ARGUMENT']], 400),
        ]);
        $this->device($this->me(), 'gone');
        $this->device($this->me(), 'garbage');
        $this->device($this->me(), 'alive');

        $note = app(Notifier::class)->notify('trading.stopped', 'Stopped.', $this->me()->id);
        $this->assertModelExists($note);
        $this->assertSame(['alive'], MobileDevice::query()->pluck('fcm_token')->all());
    }

    public function test_rate_limited_devices_are_retried_alone_later(): void
    {
        $this->configurePush();
        $this->fakeGoogle(['busy' => Http::response(['error' => ['code' => 429, 'status' => 'RESOURCE_EXHAUSTED']], 429, ['Retry-After' => '120'])]);
        $busy = $this->device($this->me(), 'busy');
        $this->device($this->me(), 'fine');
        $note = AppNotification::query()->create(['user_id' => $this->me()->id, 'type' => 'trading.stopped', 'severity' => 'warning',
            'title' => 'Trading stopped', 'message' => 'Stopped.', 'data' => []]);
        Queue::fake();

        app()->call([new SendPushNotification($note->id), 'handle']);

        Queue::assertPushed(SendPushNotification::class, fn (SendPushNotification $job) => $job->deviceIds === [$busy->id] && $job->round === 2
            && $job->delay !== null);
        $this->assertSame(2, MobileDevice::query()->count(), 'a rate limit is not a dead token');
    }

    public function test_push_failures_never_break_the_notification(): void
    {
        $this->configurePush();
        Http::fake([
            'oauth2.googleapis.com/token' => Http::response(['error' => 'invalid_grant'], 400),
            'fcm.googleapis.com/*' => Http::response([], 500),
        ]);
        $this->device($this->me(), 'phone-1');

        $note = app(Notifier::class)->notify('trading.stopped', 'Stopped.', $this->me()->id);
        $this->assertModelExists($note);
        $this->assertSame([], $this->sentTo());
        $this->assertSame(1, MobileDevice::query()->count());
    }

    public function test_engine_written_notifications_are_pushed_once_by_the_scheduler(): void
    {
        $this->configurePush();
        Queue::fake();
        $me = $this->me();
        $this->device($me, 'my-phone');
        // Written straight to the table, as the trading engine does.
        $opened = AppNotification::query()->create(['user_id' => $me->id, 'type' => 'position.opened', 'severity' => 'success',
            'title' => 'Position opened', 'message' => 'R_10 BUY opened.', 'data' => ['trade_id' => 't-1']]);
        AppNotification::query()->create(['user_id' => $this->user()->id, 'type' => 'position.opened', 'severity' => 'success',
            'title' => 'Position opened', 'message' => 'Not mine, no phone.', 'data' => []]);
        $old = AppNotification::query()->create(['user_id' => $me->id, 'type' => 'position.closed', 'severity' => 'info',
            'title' => 'Position closed', 'message' => 'Long ago.', 'data' => [], 'created_at' => now()->subHour()]);

        $this->artisan('tp:push-notifications')->assertSuccessful();
        $this->artisan('tp:push-notifications')->assertSuccessful();

        Queue::assertPushed(SendPushNotification::class, 1);
        Queue::assertPushedOn('notifications', SendPushNotification::class, fn (SendPushNotification $job) => $job->notificationId === $opened->id);
        $this->assertNotSame($old->id, $opened->id);
    }

    public function test_the_scheduler_skips_what_the_notifier_already_queued(): void
    {
        $this->configurePush();
        Queue::fake();
        $this->device($this->me(), 'my-phone');
        app(Notifier::class)->notify('trading.stopped', 'Stopped.', $this->me()->id);
        $this->artisan('tp:push-notifications')->assertSuccessful();
        Queue::assertPushed(SendPushNotification::class, 1);
    }

    public function test_deactivated_users_get_no_pushes(): void
    {
        $this->configurePush();
        $this->fakeGoogle();
        $user = $this->user();
        $this->device($user, 'their-phone');
        $note = AppNotification::query()->create(['user_id' => $user->id, 'type' => 'trading.stopped', 'severity' => 'warning',
            'title' => 'Trading stopped', 'message' => 'Stopped.', 'data' => []]);
        User::query()->whereKey($user->id)->update(['is_active' => false]);

        app()->call([new SendPushNotification($note->id), 'handle']);
        $this->assertSame([], $this->sentTo());
    }
}
