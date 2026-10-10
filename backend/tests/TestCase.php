<?php

namespace Tests;

use App\Models\SystemState;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Foundation\Testing\TestCase as BaseTestCase;
use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;

abstract class TestCase extends BaseTestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        Http::preventStrayRequests(); // tests never reach a real engine or broker
        // Requests come from the dashboard origin, like the real SPA (Sanctum stateful).
        $this->withHeaders(['Accept' => 'application/json', 'Origin' => 'http://localhost:3421', 'Referer' => 'http://localhost:3421/']);
    }

    private ?User $me = null;

    /** The user most tests act as (created on first use, provisioned like a sign-up). */
    protected function me(): User
    {
        return $this->me ??= $this->user();
    }

    /** A new user with their Beginner risk profile and trading state (stopped, DEMO). */
    protected function user(array $attributes = []): User
    {
        return User::factory()->provisioned()->create($attributes);
    }

    protected function admin(): User
    {
        return User::factory()->admin()->provisioned()->create();
    }

    /** Fake the trading engine: ['/internal/path' => response array | callable]. */
    protected function fakeEngine(array $routes): void
    {
        $fakes = [];
        foreach ($routes as $path => $response) {
            $fakes['engine.test'.$path.'*'] = is_array($response) ? Http::response($response) : $response;
        }
        Http::fake($fakes);
    }

    protected function engineDown(): void
    {
        Http::fake(['engine.test/*' => fn () => throw new ConnectionException('refused')]);
    }

    /** Pretend the engine wrote a fresh heartbeat. */
    protected function engineAlive(): void
    {
        SystemState::query()->whereKey(1)->update(['engine_heartbeat_at' => now(), 'engine_degraded' => false]);
    }
}
