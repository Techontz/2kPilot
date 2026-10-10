<?php

namespace Tests\Unit;

use App\Services\Live\LiveStream;
use PHPUnit\Framework\TestCase;

/** The pure part of the live stream: which events a fingerprint change sends. */
class LiveStreamTest extends TestCase
{
    private function prints(array $changes = []): array
    {
        $base = [
            'trading.status' => ['data' => ['kill_switch_engaged' => true, 'trading_mode' => 'DEMO', 'platform_halted' => false, 'engine_state' => 'running'], 'version' => 'a'],
            'account.balance:acc-1' => ['data' => ['account_id' => 'acc-1', 'balance' => '100.00', 'equity' => '100.00', 'currency' => 'USD', 'synced_at' => null], 'version' => ''],
            'account.balance:acc-2' => ['data' => ['account_id' => 'acc-2', 'balance' => '50.00', 'equity' => '50.00', 'currency' => 'EUR', 'synced_at' => null], 'version' => ''],
            'trade.opened' => ['data' => ['open_count' => 1], 'version' => 't1'],
            'trade.closed' => ['data' => ['closed_count' => 4], 'version' => 't2'],
            'notification' => ['data' => ['unread' => 0], 'version' => ''],
        ];

        return array_replace_recursive($base, $changes);
    }

    public function test_no_change_sends_nothing(): void
    {
        $this->assertSame([], LiveStream::diff($this->prints(), $this->prints()));
    }

    public function test_each_change_sends_its_event_with_the_new_payload(): void
    {
        $cases = [
            'trading.status' => [['trading.status' => ['data' => ['kill_switch_engaged' => false]]], ['kill_switch_engaged' => false, 'trading_mode' => 'DEMO', 'platform_halted' => false, 'engine_state' => 'running']],
            'account.balance' => [['account.balance:acc-2' => ['data' => ['balance' => '55.00']]], ['account_id' => 'acc-2', 'balance' => '55.00', 'equity' => '50.00', 'currency' => 'EUR', 'synced_at' => null]],
            'trade.opened' => [['trade.opened' => ['data' => ['open_count' => 2], 'version' => 't3']], ['open_count' => 2]],
            'trade.closed' => [['trade.closed' => ['data' => ['closed_count' => 5], 'version' => 't4']], ['closed_count' => 5]],
            'notification' => [['notification' => ['data' => ['unread' => 3], 'version' => '9']], ['unread' => 3]],
        ];
        foreach ($cases as $event => [$change, $payload]) {
            $this->assertSame([['event' => $event, 'data' => $payload]], LiveStream::diff($this->prints(), $this->prints($change)), $event);
        }
    }

    public function test_a_version_change_alone_is_reported(): void
    {
        // An open position's live P/L moved: same count, newer updated_at.
        $events = LiveStream::diff($this->prints(), $this->prints(['trade.opened' => ['version' => 't9']]));
        $this->assertSame([['event' => 'trade.opened', 'data' => ['open_count' => 1]]], $events);
    }

    public function test_one_event_per_changed_account(): void
    {
        $current = $this->prints([
            'account.balance:acc-1' => ['data' => ['equity' => '90.00']],
            'account.balance:acc-2' => ['data' => ['equity' => '60.00']],
        ]);
        $current['account.balance:acc-3'] = ['data' => ['account_id' => 'acc-3', 'balance' => '1.00', 'equity' => '1.00', 'currency' => 'USD', 'synced_at' => null], 'version' => ''];
        $events = LiveStream::diff($this->prints(), $current);
        $this->assertSame(['account.balance', 'account.balance', 'account.balance'], array_column($events, 'event'));
        $this->assertSame(['acc-1', 'acc-2', 'acc-3'], array_column(array_column($events, 'data'), 'account_id'));
    }

    public function test_wire_format(): void
    {
        $this->assertSame("event: notification\ndata: {\"unread\":2}\n\n", LiveStream::format('notification', ['unread' => 2]));
    }
}
