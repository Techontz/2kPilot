<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\Live\LiveStream;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\StreamedResponse;

/**
 * GET /api/stream — live updates for the dashboard (Server-Sent Events).
 * See App\Services\Live\LiveStream for the events. Each connection holds one
 * PHP worker for at most tradepilot.stream.max_seconds, then the browser
 * reconnects; the dashboard falls back to polling when the stream fails.
 */
class StreamController extends Controller
{
    public function __construct(private readonly LiveStream $stream) {}

    public function show(Request $request): StreamedResponse
    {
        $user = $request->user();
        // Write the session now and never touch it again: the stream must not
        // hold (or later overwrite) the session other requests of this user use.
        if ($request->hasSession()) {
            $request->session()->save();
        }
        $live = ! app()->runningUnitTests(); // tests capture the output in their own buffer

        return response()->stream(function () use ($user, $live) {
            if ($live) {
                ignore_user_abort(false);
                set_time_limit((int) config('tradepilot.stream.max_seconds', 55) + 10);
                while (ob_get_level() > 0) {
                    ob_end_flush();
                }
            }
            $this->stream->run(
                $user,
                write: function (string $chunk) use ($live) {
                    echo $chunk;
                    if ($live) {
                        flush();
                    }
                },
                sleep: fn (float $seconds) => $this->stream->sleep($seconds),
                aborted: fn () => connection_aborted() === 1,
                now: fn () => $this->stream->now(),
            );
        }, 200, [
            'Content-Type' => 'text/event-stream',
            'Cache-Control' => 'no-cache, no-transform',
            'X-Accel-Buffering' => 'no',
            'Connection' => 'keep-alive',
        ]);
    }
}
