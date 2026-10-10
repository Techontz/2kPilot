<?php

namespace App\Services\Live;

use App\Http\Controllers\Api\NotificationController;
use App\Models\SystemState;
use App\Models\Trade;
use App\Models\TradingAccount;
use App\Models\User;
use App\Services\Trading\TradingControl;
use Illuminate\Support\Facades\DB;

/**
 * Live updates for the dashboard over Server-Sent Events (GET /api/stream).
 *
 * Every few seconds a handful of cheap queries build "fingerprints" of the
 * user's OWN records; when one changes, a named event is sent and the
 * dashboard refetches what it shows. Events (wire format
 * "event: <name>\ndata: <json>\n\n"):
 *
 *   trading.status   {kill_switch_engaged, trading_mode, platform_halted, engine_state}
 *   account.balance  {account_id, balance, equity, currency, synced_at}  (one per changed account)
 *   trade.opened     {open_count}    a position opened, or its live P/L or state changed
 *   trade.closed     {closed_count}  a trade closed (or a closed one was updated)
 *   notification     {unread}        a notification arrived or was read
 *
 * A connection lasts at most tradepilot.stream.max_seconds; the browser then
 * reconnects (EventSource does this by itself, after "retry" ms).
 */
class LiveStream
{
    public function __construct(private readonly TradingControl $control) {}

    /**
     * Keyed fingerprints: "<event>" or "<event>:<id>" => {data, version}.
     * `data` is the event payload; `version` only detects changes.
     *
     * @return array<string, array{data: array, version: string}>
     */
    public function fingerprints(User $user): array
    {
        $state = $this->control->stateOf($user);
        $platform = SystemState::current();
        [$engine] = $this->control->engineState($platform);
        $out = [
            // The platform row is written on every engine heartbeat, so its
            // updated_at is NOT used: only the halt switch and the engine state.
            'trading.status' => [
                'data' => [
                    'kill_switch_engaged' => $state->kill_switch_engaged,
                    'trading_mode' => $state->trading_mode->value,
                    'platform_halted' => $platform->kill_switch_engaged,
                    'engine_state' => $engine->value,
                ],
                'version' => implode('|', [$state->updated_at?->format('Y-m-d H:i:s.u'), $platform->kill_switch_changed_at?->format('Y-m-d H:i:s.u')]),
            ],
        ];

        $accounts = TradingAccount::query()->ownedBy($user)->orderBy('id')->get(['id', 'balance', 'equity', 'currency', 'synced_at']);
        foreach ($accounts as $account) {
            $out['account.balance:'.$account->id] = [
                'data' => [
                    'account_id' => $account->id,
                    'balance' => $account->balance,
                    'equity' => $account->equity,
                    'currency' => $account->currency,
                    'synced_at' => $account->synced_at?->toIso8601String(),
                ],
                'version' => '',
            ];
        }

        $trades = Trade::query()->ownedBy($user)->whereIn('status', ['OPEN', 'CLOSED'])->groupBy('status')
            ->get(['status', DB::raw('COUNT(*) as n'), DB::raw('MAX(updated_at) as v')])->keyBy('status');
        foreach (['OPEN' => ['trade.opened', 'open_count'], 'CLOSED' => ['trade.closed', 'closed_count']] as $status => [$event, $field]) {
            $row = $trades->get($status);
            $out[$event] = ['data' => [$field => (int) ($row->n ?? 0)], 'version' => (string) ($row->v ?? '')];
        }

        $inbox = NotificationController::inbox($user)->whereNull('read_at')
            ->toBase()->selectRaw('COUNT(*) as n, MAX(id) as last_id')->first();
        $out['notification'] = ['data' => ['unread' => (int) ($inbox->n ?? 0)], 'version' => (string) ($inbox->last_id ?? '')];

        return $out;
    }

    /**
     * The events to send for a change from $previous to $current fingerprints
     * (an empty $previous reports everything).
     *
     * @return list<array{event: string, data: array}>
     */
    public static function diff(array $previous, array $current): array
    {
        $events = [];
        foreach ($current as $key => $print) {
            if (! array_key_exists($key, $previous) || $previous[$key] !== $print) {
                $events[] = ['event' => explode(':', (string) $key, 2)[0], 'data' => $print['data']];
            }
        }

        return $events;
    }

    public static function format(string $event, array $data): string
    {
        return "event: {$event}\ndata: ".json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)."\n\n";
    }

    /**
     * The stream loop. The I/O is passed in so tests run it without waiting:
     * $write(string), $sleep(float seconds), $aborted(): bool, $now(): float seconds.
     */
    public function run(User $user, callable $write, callable $sleep, callable $aborted, callable $now): void
    {
        $max = max(0, (int) config('tradepilot.stream.max_seconds', 55));
        $interval = max(0.25, (float) config('tradepilot.stream.interval_seconds', 2));
        $heartbeat = max(1, (int) config('tradepilot.stream.heartbeat_seconds', 15));
        $start = $now();
        $write("retry: 3000\n\n");
        $write(": connected\n\n");
        $lastWrite = $start;
        $previous = $this->fingerprints($user); // the baseline: nothing is sent for it

        while (! $aborted() && $now() - $start + $interval <= $max) {
            $sleep($interval);
            if ($aborted()) {
                return;
            }
            $current = $this->fingerprints($user);
            foreach (self::diff($previous, $current) as $event) {
                $write(self::format($event['event'], $event['data']));
                $lastWrite = $now();
            }
            $previous = $current;
            if ($now() - $lastWrite >= $heartbeat) {
                $write(": ping\n\n");
                $lastWrite = $now();
            }
        }
    }

    /** Real time, in seconds. */
    public function now(): float
    {
        return microtime(true);
    }

    public function sleep(float $seconds): void
    {
        usleep((int) round($seconds * 1_000_000));
    }
}
