<?php

namespace Tests\Feature;

use App\Models\User;
use App\Services\Live\LiveStream;
use App\Services\Notifier;
use App\Services\Trading\TradingControl;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

/** GET /api/stream: Server-Sent Events with the user's own changes only. */
class StreamTest extends TestCase
{
    use CreatesTradingData;

    public function test_fingerprints_only_follow_my_own_records(): void
    {
        $me = $this->me();
        $other = $this->user();
        $mine = $this->account();
        $theirs = $this->account([], owner: $other);
        $stream = app(LiveStream::class);
        $before = $stream->fingerprints($me);
        $this->assertArrayHasKey('account.balance:'.$mine->id, $before);
        $this->assertArrayNotHasKey('account.balance:'.$theirs->id, $before);

        // Another user's trades, balances, notifications and STOP switch change nothing for me.
        $this->openTrade($theirs);
        $this->closedTrade($theirs, 10);
        $theirs->update(['balance' => '1', 'equity' => '1']);
        app(Notifier::class)->notify('trading.stopped', 'not yours', $other->id);
        app(TradingControl::class)->resume($other);
        $this->assertSame([], LiveStream::diff($before, $stream->fingerprints($me)));

        // My own changes do.
        $this->travel(1)->seconds();
        $this->openTrade($mine);
        $this->closedTrade($mine, -5);
        $mine->update(['balance' => '9990.5']);
        app(Notifier::class)->notify('trading.stopped', 'yours', $me->id);
        app(TradingControl::class)->resume($me);
        $events = LiveStream::diff($before, $stream->fingerprints($me));
        $byName = array_column($events, 'data', 'event');
        $this->assertEqualsCanonicalizing(['trading.status', 'account.balance', 'trade.opened', 'trade.closed', 'notification'], array_keys($byName));
        $this->assertFalse($byName['trading.status']['kill_switch_engaged']);
        $this->assertSame(['account_id' => $mine->id, 'balance' => '9990.500000', 'equity' => '10000.000000', 'currency' => 'USD', 'synced_at' => null], $byName['account.balance']);
        $this->assertSame(1, $byName['trade.opened']['open_count']);
        $this->assertSame(1, $byName['trade.closed']['closed_count']);
        $this->assertSame(2, $byName['notification']['unread']); // mine + "Trading resumed"
    }

    public function test_the_stream_sends_events_for_changes_after_the_baseline(): void
    {
        config(['tradepilot.stream.max_seconds' => 6, 'tradepilot.stream.interval_seconds' => 2, 'tradepilot.stream.heartbeat_seconds' => 3]);
        $me = $this->me();
        $clock = 0.0;
        $out = '';
        $sleeps = 0;
        app(LiveStream::class)->run($me,
            write: function (string $chunk) use (&$out) {
                $out .= $chunk;
            },
            sleep: function (float $s) use (&$clock, &$sleeps, $me) {
                $clock += $s;
                if (++$sleeps === 1) {
                    app(TradingControl::class)->resume($me); // a change during the first wait
                }
            },
            aborted: fn () => false,
            now: function () use (&$clock) {
                return $clock;
            },
        );
        $this->assertSame(3, $sleeps); // 6 s / 2 s
        $this->assertStringStartsWith("retry: 3000\n\n: connected\n\n", $out);
        $this->assertSame(1, substr_count($out, 'event: trading.status'));
        $this->assertStringContainsString('"kill_switch_engaged":false', $out);
        $this->assertStringContainsString('event: notification', $out); // "Trading resumed" notification
        $this->assertStringContainsString(": ping\n\n", $out); // quiet for 4 s > 3 s heartbeat
    }

    public function test_the_stream_stops_when_the_browser_goes_away(): void
    {
        $out = '';
        $checks = 0;
        app(LiveStream::class)->run($this->me(), function (string $c) use (&$out) {
            $out .= $c;
        }, fn () => null, function () use (&$checks) {
            return ++$checks > 1;
        }, fn () => 0.0);
        $this->assertSame("retry: 3000\n\n: connected\n\n", $out);
    }

    public function test_get_stream_returns_an_event_stream(): void
    {
        config(['tradepilot.stream.max_seconds' => 0]);
        $response = $this->actingAs($this->me())->get('/api/stream')->assertOk();
        $this->assertStringStartsWith('text/event-stream', $response->headers->get('Content-Type'));
        $this->assertStringContainsString('no-cache', $response->headers->get('Cache-Control'));
        $this->assertStringContainsString('no-transform', $response->headers->get('Cache-Control'));
        $this->assertSame('no', $response->headers->get('X-Accel-Buffering'));
        $this->assertStringStartsWith("retry: 3000\n\n", $response->streamedContent());
    }

    public function test_get_stream_needs_a_signed_in_user(): void
    {
        $this->getJson('/api/stream')->assertUnauthorized();
        $this->get('/api/stream', ['Accept' => 'text/event-stream'])->assertUnauthorized(); // what EventSource sends
        $inactive = User::factory()->provisioned()->create(['is_active' => false]);
        $this->actingAs($inactive)->getJson('/api/stream')->assertUnauthorized()->assertJsonPath('code', 'account_disabled');
    }
}
