<?php

namespace Tests\Feature;

use App\Models\SystemState;
use App\Models\User;
use App\Services\Engine\EngineClient;
use App\Services\Engine\EngineException;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Http;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class CommandsAndEngineClientTest extends TestCase
{
    use CreatesTradingData;

    public function test_engine_requests_are_hmac_signed(): void
    {
        Http::fake(['engine.test/*' => Http::response(['ok' => true])]);
        app(EngineClient::class)->post('/internal/orders', ['a' => 1]);
        app(EngineClient::class)->get('/internal/accounts/x/quotes', ['symbols' => 'frxEURUSD,R_100']);
        Http::assertSent(function (Request $r) {
            $path = parse_url($r->url(), PHP_URL_PATH).(parse_url($r->url(), PHP_URL_QUERY) ? '?'.parse_url($r->url(), PHP_URL_QUERY) : '');
            $expected = hash_hmac('sha256', implode("\n", [
                $r->method(), $path, $r->header('X-Engine-Timestamp')[0], $r->header('X-Engine-Nonce')[0], hash('sha256', $r->body()),
            ]), config('tradepilot.engine.secret'));
            $this->assertSame($expected, $r->header('X-Engine-Signature')[0]);
            $this->assertEqualsWithDelta(time(), (int) $r->header('X-Engine-Timestamp')[0], 5);

            return true;
        });
    }

    public function test_engine_errors_and_secret_mismatch(): void
    {
        Http::fake(['engine.test/*' => Http::response(['error' => ['code' => 'unauthorized', 'message' => 'Request not signed']], 401)]);
        try {
            app(EngineClient::class)->get('/internal/health');
            $this->fail('expected an exception');
        } catch (EngineException $e) {
            $this->assertStringContainsString('ENGINE_API_SECRET', $e->getMessage());
            $this->assertSame(502, $e->httpStatus());
        }
    }

    public function test_tp_user_rejects_a_weak_password_and_creates_a_user_with_a_strong_password(): void
    {
        $this->artisan('tp:user', ['--email' => 'Me@Example.com', '--name' => 'Me', '--password-stdin' => true])
            ->expectsOutputToContain('password'); // fgets(STDIN) is empty in tests → validation fails
        $this->assertDatabaseCount('users', 0);
    }

    public function test_watchdog_notifies_once_per_outage_and_on_recovery(): void
    {
        SystemState::query()->whereKey(1)->update(['engine_heartbeat_at' => now()->subMinutes(5)]);
        $this->artisan('tp:engine-watchdog')->assertSuccessful();
        $this->artisan('tp:engine-watchdog')->assertSuccessful();
        $this->assertDatabaseCount('notifications', 1);
        $this->assertDatabaseHas('notifications', ['type' => 'system.engine_offline', 'severity' => 'critical']);
        $this->engineAlive();
        $this->artisan('tp:engine-watchdog')->assertSuccessful();
        $this->assertDatabaseHas('notifications', ['type' => 'system.engine_online']);
    }

    public function test_daily_summary_and_prune(): void
    {
        $this->travelTo(now()->setTime(12, 0)); // 'today' must not depend on when the suite runs
        $account = $this->account();
        $this->closedTrade($account, 25, '-1 minute');
        $this->artisan('tp:daily-summary')->assertSuccessful();
        $this->assertDatabaseHas('notifications', ['type' => 'report.daily']);
        $this->artisan('tp:prune', ['--days' => 30])->assertSuccessful();
    }

    public function test_fx_keys_writes_matching_values_to_both_env_files(): void
    {
        $dir = sys_get_temp_dir().'/tpkeys-'.uniqid();
        mkdir($dir);
        file_put_contents("{$dir}/engine.env", "DATABASE_URL=x\n");
        $this->artisan('tp:keys', ['--engine-env' => "{$dir}/engine.env"])->assertSuccessful();
        $engine = file_get_contents("{$dir}/engine.env");
        $this->assertMatchesRegularExpression('/^BROKER_CREDENTIALS_KEY=base64:[A-Za-z0-9+\/=]{44}$/m', $engine);
        $this->assertMatchesRegularExpression('/^ENGINE_API_SECRET=\S{64}$/m', $engine);
        $this->assertStringContainsString('DATABASE_URL=x', $engine);
    }

    public function test_schedule_is_registered(): void
    {
        $this->artisan('schedule:list')->expectsOutputToContain('tp:engine-watchdog')->assertSuccessful();
        $this->assertSame(0, User::query()->count());
    }

    public function test_tp_user_creates_a_provisioned_admin(): void
    {
        $this->artisan('tp:user', ['--email' => 'Admin@Example.com', '--name' => 'Admin', '--role' => 'admin'])
            ->expectsQuestion('Password (10+ characters, mixed case, a number)', 'Very-Strong-42')
            ->expectsQuestion('Repeat the password', 'Very-Strong-42')
            ->assertSuccessful();
        $user = User::query()->where('email', 'admin@example.com')->firstOrFail();
        $this->assertTrue($user->isAdmin());
        $this->assertDatabaseHas('risk_profiles', ['user_id' => $user->id, 'name' => 'Beginner']);
        $this->assertDatabaseHas('user_trading_states', ['user_id' => $user->id, 'kill_switch_engaged' => true, 'trading_mode' => 'DEMO']);
        $this->artisan('tp:user', ['--email' => 'x@example.com', '--name' => 'X', '--role' => 'owner'])
            ->expectsQuestion('Password (10+ characters, mixed case, a number)', 'Very-Strong-42')
            ->expectsQuestion('Repeat the password', 'Very-Strong-42')
            ->assertFailed();
    }
}
