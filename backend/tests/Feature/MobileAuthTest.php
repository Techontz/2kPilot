<?php

namespace Tests\Feature;

use App\Enums\TradingMode;
use App\Models\MobileDevice;
use App\Models\RiskProfile;
use App\Models\SystemState;
use App\Models\User;
use App\Models\UserTradingState;
use App\Services\Mfa\TwoFactorService;
use App\Services\Users\UserProvisioner;
use Database\Factories\UserFactory;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\RateLimiter;
use Laravel\Sanctum\PersonalAccessToken;
use PragmaRX\Google2FA\Google2FA;
use Tests\TestCase;

/** The mobile app: bearer-token sign-in, devices, and what stays on the website. */
class MobileAuthTest extends TestCase
{
    /** Requests like the native app: no Origin/Referer (stateless), optionally a bearer token. */
    private function asApp(?string $token = null): static
    {
        $this->app['auth']->forgetGuards(); // nothing carried over from a previous request
        $this->flushHeaders();
        $this->withHeaders(['Accept' => 'application/json']);
        if ($token !== null) {
            $this->withToken($token);
        }

        return $this;
    }

    /** Back to the dashboard's cookie session requests (as in TestCase::setUp). */
    private function asWebsite(): static
    {
        $this->app['auth']->forgetGuards();
        $this->flushHeaders();
        $this->withHeaders(['Accept' => 'application/json', 'Origin' => 'http://localhost:3421', 'Referer' => 'http://localhost:3421/']);

        return $this;
    }

    private function login(User $user, string $device = 'Pixel 9'): string
    {
        return $this->asApp()->postJson('/api/mobile/auth/login', [
            'email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => $device,
        ])->assertOk()->json('token');
    }

    /** Turn MFA on for $user; returns [secret, recovery codes]. */
    private function enableMfa(User $user): array
    {
        $mfa = app(TwoFactorService::class);
        $secret = $mfa->begin($user)['secret'];
        $codes = $mfa->confirm($user->fresh(), (new Google2FA)->getCurrentOtp($secret));
        Cache::forget("mfa:last:{$user->id}"); // let the tests use the current code again

        return [$secret, $codes];
    }

    private function otp(string $secret): string
    {
        return (new Google2FA)->getCurrentOtp($secret);
    }

    // ── Sign-in ───────────────────────────────────────────────────────

    public function test_login_without_mfa_returns_a_bearer_token(): void
    {
        $user = $this->user(['email' => 'conrad@example.com']);
        $body = $this->asApp()->postJson('/api/mobile/auth/login', [
            'email' => 'Conrad@Example.com', 'password' => UserFactory::PASSWORD, 'device_name' => 'Pixel 9',
        ])->assertOk()->assertJsonPath('token_type', 'Bearer')
            ->assertJsonPath('user.email', 'conrad@example.com')
            ->assertJsonPath('user.mfa_enabled', false)
            ->assertJsonStructure(['token', 'token_type', 'expires_at', 'user' => ['id', 'name', 'email', 'role', 'mfa_enabled', 'mfa_required', 'last_login_at']])
            ->json();

        $token = PersonalAccessToken::findToken($body['token']);
        $this->assertSame($user->id, $token->tokenable_id);
        $this->assertSame('Pixel 9', $token->name);
        $this->assertSame(['mobile'], $token->abilities);
        $this->assertEqualsWithDelta(now()->addDays(30)->timestamp, $token->expires_at->timestamp, 5);
        $this->assertSame($token->expires_at->toIso8601String(), $body['expires_at']);
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.mobile_login', 'outcome' => 'success', 'actor_user_id' => $user->id]);
        // The same user shape as GET /api/auth/me.
        $this->asApp($body['token'])->getJson('/api/auth/me')->assertOk()->assertJsonPath('user', $body['user']);
    }

    public function test_token_lifetime_comes_from_config(): void
    {
        config(['tradepilot.mobile.token_days' => 7]);
        $token = PersonalAccessToken::findToken($this->login($this->me()));
        $this->assertEqualsWithDelta(now()->addDays(7)->timestamp, $token->expires_at->timestamp, 5);
    }

    public function test_wrong_password_inactive_user_and_unknown_email_get_the_same_answer(): void
    {
        $this->user(['email' => 'conrad@example.com']);
        $inactive = User::factory()->inactive()->create();
        $answers = [
            $this->asApp()->postJson('/api/mobile/auth/login', ['email' => 'conrad@example.com', 'password' => 'nope', 'device_name' => 'x']),
            $this->asApp()->postJson('/api/mobile/auth/login', ['email' => 'ghost@example.com', 'password' => 'nope', 'device_name' => 'x']),
            $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $inactive->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x']),
        ];
        foreach ($answers as $answer) {
            $answer->assertStatus(422)->assertExactJson(['message' => 'Email or password is incorrect.', 'code' => 'invalid_credentials']);
        }
        $this->assertSame(0, PersonalAccessToken::query()->count());
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.mobile_login', 'outcome' => 'failure']);
    }

    public function test_device_name_is_required_and_limited(): void
    {
        $user = $this->me();
        $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])
            ->assertStatus(422)->assertJsonValidationErrors('device_name');
        $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => str_repeat('x', 101)])
            ->assertStatus(422)->assertJsonValidationErrors('device_name');
    }

    public function test_login_is_rate_limited_and_shares_the_web_budget(): void
    {
        $user = $this->user(['email' => 'conrad@example.com']);
        foreach (range(1, 3) as $_) {
            $this->asApp()->postJson('/api/mobile/auth/login', ['email' => 'conrad@example.com', 'password' => 'wrong', 'device_name' => 'x'])->assertStatus(422);
        }
        foreach (range(1, 2) as $_) {
            $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => 'wrong'])->assertStatus(422);
        }
        $this->asApp()->postJson('/api/mobile/auth/login', ['email' => 'conrad@example.com', 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])
            ->assertStatus(429);
        $this->assertSame(0, $user->tokens()->count());
    }

    public function test_completed_logins_do_not_use_up_attempts(): void
    {
        $user = $this->me();
        foreach (range(1, 7) as $_) {
            $this->login($user);
        }
        $this->assertSame(7, $user->tokens()->count());
    }

    public function test_with_mfa_the_password_returns_a_challenge_and_the_code_returns_the_token(): void
    {
        $user = $this->me();
        [$secret] = $this->enableMfa($user);

        $first = $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'iPhone'])
            ->assertOk()->assertJsonPath('mfa_required', true);
        $this->assertArrayNotHasKey('token', $first->json());
        $challenge = $first->json('mfa_token');
        $this->assertGreaterThanOrEqual(40, strlen($challenge));
        $this->assertSame(0, $user->tokens()->count());

        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $challenge, 'code' => '000000'])
            ->assertStatus(422)->assertJsonPath('code', 'invalid_code');
        $body = $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $challenge, 'code' => $this->otp($secret)])
            ->assertOk()->assertJsonPath('token_type', 'Bearer')->assertJsonPath('user.mfa_enabled', true)->json();
        $this->assertSame('iPhone', PersonalAccessToken::findToken($body['token'])->name);
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.mobile_login', 'outcome' => 'success', 'actor_user_id' => $user->id]);

        // Single use.
        Cache::forget("mfa:last:{$user->id}");
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $challenge, 'code' => $this->otp($secret)])
            ->assertStatus(422)->assertJsonPath('code', 'mfa_expired');
    }

    public function test_a_recovery_code_also_completes_the_mobile_sign_in(): void
    {
        $user = $this->me();
        [, $codes] = $this->enableMfa($user);
        $challenge = $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])->json('mfa_token');
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $challenge, 'code' => $codes[0]])->assertOk()->assertJsonStructure(['token']);
    }

    public function test_the_mfa_challenge_expires_after_five_minutes(): void
    {
        $user = $this->me();
        [$secret] = $this->enableMfa($user);
        $challenge = $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])->json('mfa_token');
        $this->travel(301)->seconds();
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $challenge, 'code' => $this->otp($secret)])
            ->assertStatus(422)->assertJsonPath('code', 'mfa_expired');
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => 'made-up', 'code' => $this->otp($secret)])
            ->assertStatus(422)->assertJsonPath('code', 'mfa_expired');
        $this->assertSame(0, $user->tokens()->count());
    }

    public function test_wrong_codes_lock_the_user_and_consume_the_challenge(): void
    {
        $user = $this->me();
        [$secret] = $this->enableMfa($user);
        $challenge = fn () => $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])->json('mfa_token');

        // Misses are counted per USER: the mfa limiter (5 per pending user + IP) lets the 5th through to lock.
        $first = $challenge();
        foreach (range(1, 4) as $_) {
            $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $first, 'code' => '000000'])->assertStatus(422);
        }
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $first, 'code' => '000000'])
            ->assertStatus(429)->assertJsonPath('code', 'mfa_locked');
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.mfa.locked', 'target_id' => $user->id]);
        // The challenge is consumed, and the lock holds for a fresh challenge.
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $first, 'code' => $this->otp($secret)])
            ->assertStatus(422)->assertJsonPath('code', 'mfa_expired');
        $this->assertTrue(Cache::has("mfa:locked:{$user->id}"));
        RateLimiter::clear(md5('mfa'.'mfa:'.$user->id.'|127.0.0.1')); // the request limiter, so the lock itself answers
        $second = $challenge();
        $this->assertNotNull($second, 'the password step still answers');
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $second, 'code' => $this->otp($secret)])
            ->assertStatus(429)->assertJsonPath('code', 'mfa_locked');
        $this->assertSame(0, $user->tokens()->count());
    }

    public function test_the_mfa_step_is_throttled_per_pending_user(): void
    {
        $user = $this->me();
        $this->enableMfa($user);
        $challenge = $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])->json('mfa_token');
        foreach (range(1, 4) as $_) {
            $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $challenge, 'code' => '000000'])->assertStatus(422);
        }
        // 5th miss locks; afterwards the limiter keyed on this pending user answers 429 too.
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $challenge, 'code' => '000000'])->assertStatus(429);
        Cache::forget("mfa:locked:{$user->id}");
        $fresh = $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])->json('mfa_token');
        $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $fresh, 'code' => '000000'])
            ->assertStatus(429)->assertHeader('Retry-After');
    }

    public function test_an_mfa_required_answer_counts_against_the_login_budget(): void
    {
        $user = $this->me();
        $this->enableMfa($user);
        foreach (range(1, 5) as $_) {
            $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])
                ->assertOk()->assertJsonPath('mfa_required', true);
        }
        $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])->assertStatus(429);
    }

    // ── Bearer tokens on the existing API ────────────────────────────

    public function test_a_bearer_token_reaches_the_existing_api_without_csrf_or_session(): void
    {
        $token = $this->login($this->me());
        $this->asApp($token)->getJson('/api/overview')->assertOk()->assertJsonPath('robot.trading_mode', 'DEMO');
        $this->asApp($token)->getJson('/api/trading/status')->assertOk()->assertJsonPath('trading_mode', 'DEMO')
            ->assertHeader('X-Frame-Options', 'DENY')->assertHeaderMissing('Set-Cookie');
        $this->asApp($token)->getJson('/api/history')->assertOk()->assertJsonStructure(['data']);
        $this->asApp()->getJson('/api/overview')->assertUnauthorized();
        $this->asApp('1|not-a-real-token')->getJson('/api/overview')->assertUnauthorized();
        $this->assertNotNull(PersonalAccessToken::findToken($token)->last_used_at);
    }

    public function test_tokens_expire(): void
    {
        $token = $this->login($this->me());
        $this->travel(29)->days();
        $this->asApp($token)->getJson('/api/auth/me')->assertOk();
        $this->travel(2)->days();
        $this->asApp($token)->getJson('/api/auth/me')->assertUnauthorized();
    }

    public function test_bearer_requests_respect_active_mfa_enrolment_and_policies(): void
    {
        $me = $this->me();
        $token = $this->login($me);

        // Policies: another user's records stay out of reach.
        $other = $this->user();
        $profile = RiskProfile::query()->where('user_id', $other->id)->firstOrFail();
        $this->asApp($token)->putJson("/api/risk/profiles/{$profile->id}", ['name' => 'Mine now'])->assertForbidden();

        // mfa.enrolled
        config(['tradepilot.mfa.required' => true]);
        $this->asApp($token)->getJson('/api/overview')->assertForbidden()->assertJsonPath('code', 'mfa_enrollment_required');
        config(['tradepilot.mfa.required' => false]);

        // Throttle: the per-user API budget applies to tokens too.
        config(['tradepilot.rate_limits.api_per_minute' => 1]);
        $this->travel(2)->minutes(); // a fresh one-minute window
        $this->asApp($token)->getJson('/api/auth/me')->assertOk();
        $this->asApp($token)->getJson('/api/auth/me')->assertStatus(429);
        config(['tradepilot.rate_limits.api_per_minute' => 300]);

        // active: a deactivated user's tokens are revoked.
        $me->forceFill(['is_active' => false])->save();
        $this->asApp($token)->getJson('/api/trading/status')->assertUnauthorized();
        $this->assertSame(0, $me->tokens()->count());
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.token_revoked', 'actor_user_id' => $me->id]);
    }

    public function test_an_inactive_users_leftover_token_is_refused_and_deleted(): void
    {
        $me = $this->me();
        $token = $this->login($me);
        User::query()->whereKey($me->id)->update(['is_active' => false]); // bypasses the model hook
        $this->asApp($token)->getJson('/api/trading/status')->assertUnauthorized()->assertJsonPath('code', 'account_disabled');
        $this->assertSame(0, $me->tokens()->count());
    }

    public function test_cookie_sessions_from_the_dashboard_keep_working(): void
    {
        $user = $this->user(['email' => 'conrad@example.com']);
        $this->login($user);
        $this->asWebsite();
        $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => UserFactory::PASSWORD])->assertOk();
        $this->getJson('/api/auth/me')->assertOk()->assertJsonPath('user.email', 'conrad@example.com');
        $this->putJson('/api/auth/password', ['current_password' => 'wrong', 'password' => 'An0ther-Secret-Pass', 'password_confirmation' => 'An0ther-Secret-Pass'])
            ->assertStatus(422)->assertJsonPath('code', 'password_incorrect'); // reaches the controller: not web_only
    }

    // ── Logout and device sessions ───────────────────────────────────

    public function test_logout_revokes_the_token_and_its_push_registration(): void
    {
        $me = $this->me();
        $token = $this->login($me);
        $other = $this->login($me, 'Tablet');
        $this->asApp($token)->postJson('/api/mobile/devices', ['fcm_token' => 'fcm-phone', 'platform' => 'android'])->assertOk();
        $this->asApp($other)->postJson('/api/mobile/devices', ['fcm_token' => 'fcm-tablet', 'platform' => 'ios'])->assertOk();

        $this->asApp($token)->postJson('/api/mobile/auth/logout')->assertOk()->assertExactJson(['ok' => true]);
        $this->asApp($token)->getJson('/api/auth/me')->assertUnauthorized();
        $this->asApp($other)->getJson('/api/auth/me')->assertOk();
        $this->assertSame(['fcm-tablet'], MobileDevice::query()->pluck('fcm_token')->all());
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.mobile_logout', 'actor_user_id' => $me->id]);
    }

    public function test_mobile_logout_needs_a_mobile_token(): void
    {
        $this->actingAs($this->me())->postJson('/api/mobile/auth/logout')->assertForbidden()->assertJsonPath('code', 'mobile_token_required');
    }

    public function test_the_device_list_and_revoking_one_device(): void
    {
        $me = $this->me();
        $phone = $this->login($me, 'Phone');
        $tablet = $this->login($me, 'Tablet');
        $theirs = $this->login($this->user(), 'Not mine');
        $theirId = PersonalAccessToken::findToken($theirs)->id;
        $tabletId = PersonalAccessToken::findToken($tablet)->id;

        $list = $this->asApp($phone)->getJson('/api/auth/tokens')->assertOk()->assertJsonCount(2)->json();
        $this->assertEqualsCanonicalizing(['Phone', 'Tablet'], array_column($list, 'name'));
        $this->assertSame([true, false], [collect($list)->firstWhere('name', 'Phone')['current'], collect($list)->firstWhere('name', 'Tablet')['current']]);
        $this->assertSame(['id', 'name', 'created_at', 'last_used_at', 'expires_at', 'current'], array_keys($list[0]));

        // From the website (cookie session): same list, none is "current".
        $this->asWebsite();
        $web = $this->actingAs($me)->getJson('/api/auth/tokens')->assertOk()->assertJsonCount(2)->json();
        $this->assertSame([false, false], array_column($web, 'current'));

        $this->asApp($phone)->deleteJson("/api/auth/tokens/{$theirId}")->assertNotFound()->assertJsonPath('code', 'not_found');
        $this->asApp($phone)->deleteJson('/api/auth/tokens/abc')->assertNotFound();
        $this->assertNotNull(PersonalAccessToken::find($theirId));

        $this->asApp($tablet)->postJson('/api/mobile/devices', ['fcm_token' => 'fcm-tablet', 'platform' => 'ios'])->assertOk();
        $this->asApp($phone)->deleteJson("/api/auth/tokens/{$tabletId}")->assertOk()->assertExactJson(['ok' => true]);
        $this->asApp($tablet)->getJson('/api/auth/me')->assertUnauthorized();
        $this->assertSame(0, MobileDevice::query()->count());
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.token_revoked', 'target_id' => (string) $tabletId]);
    }

    public function test_changing_the_password_on_the_website_revokes_every_mobile_token(): void
    {
        $me = $this->me();
        $token = $this->login($me);
        $this->asApp($token)->postJson('/api/mobile/devices', ['fcm_token' => 'fcm-phone', 'platform' => 'android'])->assertOk();
        $this->asWebsite();
        $new = 'An0ther-Secret-Pass';
        $this->actingAs($me)->putJson('/api/auth/password', ['current_password' => UserFactory::PASSWORD, 'password' => $new, 'password_confirmation' => $new])->assertOk();

        $this->assertSame(0, $me->tokens()->count());
        $this->assertSame(0, MobileDevice::query()->count());
        $this->asApp($token)->getJson('/api/auth/me')->assertUnauthorized();
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.token_revoked', 'actor_user_id' => $me->id]);
    }

    public function test_turning_mfa_off_on_the_website_revokes_every_mobile_token(): void
    {
        $me = $this->me();
        [$secret] = $this->enableMfa($me);
        $challenge = $this->asApp()->postJson('/api/mobile/auth/login', ['email' => $me->email, 'password' => UserFactory::PASSWORD, 'device_name' => 'x'])->json('mfa_token');
        $token = $this->asApp()->postJson('/api/mobile/auth/mfa', ['mfa_token' => $challenge, 'code' => $this->otp($secret)])->json('token');
        Cache::forget("mfa:last:{$me->id}");

        $this->asWebsite();
        $this->actingAs($me->fresh())->postJson('/api/auth/mfa/disable', ['password' => UserFactory::PASSWORD, 'code' => $this->otp($secret)])->assertOk();

        $this->assertSame(0, $me->tokens()->count());
        $this->asApp($token)->getJson('/api/auth/me')->assertUnauthorized();
    }

    // ── Real money and security settings stay on the website ─────────

    public function test_a_token_cannot_enter_live_mode(): void
    {
        $token = $this->login($this->me());
        $this->asApp($token)->putJson('/api/trading/mode', ['mode' => 'LIVE', 'password' => UserFactory::PASSWORD, 'confirmation_phrase' => 'ENABLE LIVE TRADING'])
            ->assertForbidden()
            ->assertExactJson(['message' => 'Authorize real-money trading on the 2kPilot website.', 'code' => 'live_requires_web']);
        $this->assertSame(TradingMode::Demo, UserTradingState::query()->find($this->me()->id)->trading_mode);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.mode.change_denied', 'outcome' => 'denied']);
    }

    public function test_a_token_can_return_to_demo(): void
    {
        $me = $this->me();
        UserTradingState::query()->whereKey($me->id)->update(['trading_mode' => 'LIVE', 'kill_switch_engaged' => true, 'live_authorized_at' => now()]);
        $token = $this->login($me);
        $this->asApp($token)->putJson('/api/trading/mode', ['mode' => 'DEMO'])->assertOk()->assertJsonPath('trading_mode', 'DEMO');
        $this->assertSame(TradingMode::Demo, UserTradingState::query()->find($me->id)->trading_mode);
    }

    public function test_a_token_can_stop_and_start_trading(): void
    {
        $me = $this->me();
        $token = $this->login($me);
        $this->asApp($token)->postJson('/api/trading/resume', ['confirm' => true])->assertOk()->assertJsonPath('kill_switch_engaged', false);
        $this->asApp($token)->postJson('/api/trading/stop', ['reason' => 'from my phone'])->assertOk()->assertJsonPath('kill_switch_engaged', true);
        $this->assertTrue(UserTradingState::query()->find($me->id)->kill_switch_engaged);
        $this->fakeEngine(['/internal/positions/close-all' => ['closed' => 0, 'failed' => []]]);
        $this->asApp($token)->postJson('/api/trading/close-positions', ['confirm' => true])->assertOk();
    }

    public function test_starting_in_live_mode_from_a_token_still_needs_the_live_confirmation(): void
    {
        config(['tradepilot.live_trading_enabled' => true]);
        $me = $this->me();
        UserTradingState::query()->whereKey($me->id)->update(['trading_mode' => 'LIVE', 'kill_switch_engaged' => true, 'live_authorized_at' => now()]);
        $token = $this->login($me);
        $this->asApp($token)->postJson('/api/trading/resume', ['confirm' => true])->assertStatus(409);
        $this->assertTrue(UserTradingState::query()->find($me->id)->kill_switch_engaged);
    }

    public function test_password_mfa_and_platform_operations_are_website_only(): void
    {
        $admin = $this->admin();
        $token = $this->login($admin);
        $webOnly = [
            ['putJson', '/api/auth/password', ['current_password' => UserFactory::PASSWORD, 'password' => 'An0ther-Secret-Pass', 'password_confirmation' => 'An0ther-Secret-Pass']],
            ['postJson', '/api/auth/mfa/setup', ['password' => UserFactory::PASSWORD]],
            ['postJson', '/api/auth/mfa/confirm', ['code' => '123456']],
            ['postJson', '/api/auth/mfa/disable', ['password' => UserFactory::PASSWORD, 'code' => '123456']],
            ['postJson', '/api/auth/mfa/recovery-codes', ['password' => UserFactory::PASSWORD]],
            ['postJson', '/api/admin/halt', ['reason' => 'from a phone']],
            ['postJson', '/api/admin/resume', ['confirm' => true]],
        ];
        foreach ($webOnly as [$method, $uri, $body]) {
            $this->asApp($token)->{$method}($uri, $body)->assertForbidden()->assertJsonPath('code', 'web_only');
        }
        $this->assertTrue(Hash::check(UserFactory::PASSWORD, $admin->fresh()->password));
        $this->assertFalse((bool) SystemState::current()->platform_halted);
    }

    public function test_a_token_can_edit_risk_profiles_and_read_notifications(): void
    {
        $me = $this->me();
        $token = $this->login($me);
        $profile = RiskProfile::query()->where('user_id', $me->id)->firstOrFail();
        $body = array_merge($profile->only(array_keys(UserProvisioner::BEGINNER_LIMITS)), ['name' => $profile->name, 'max_daily_loss_pct' => 1.5]);
        $this->asApp($token)->putJson("/api/risk/profiles/{$profile->id}", $body)->assertOk()->assertJsonPath('max_daily_loss_pct', '1.500');
        $this->asApp($token)->getJson('/api/notifications')->assertOk();
        $this->asApp($token)->postJson('/api/notifications/read')->assertOk();
    }

    // ── Push registration ────────────────────────────────────────────

    public function test_device_registration_is_upserted_and_scoped_to_the_user(): void
    {
        $me = $this->me();
        $mine = $this->login($me);
        $long = str_repeat('a', 4096);
        $this->asApp($mine)->postJson('/api/mobile/devices', ['fcm_token' => $long, 'platform' => 'android', 'app_version' => '1.0.0'])
            ->assertOk()->assertExactJson(['ok' => true]);
        $this->asApp($mine)->postJson('/api/mobile/devices', ['fcm_token' => $long, 'platform' => 'android', 'app_version' => '1.0.1'])->assertOk();
        $device = MobileDevice::query()->sole();
        $this->assertSame($me->id, $device->user_id);
        $this->assertSame('1.0.1', $device->app_version);
        $this->assertSame(PersonalAccessToken::findToken($mine)->id, $device->personal_access_token_id);
        $this->assertSame($long, $device->fcm_token);
        $this->assertArrayNotHasKey('fcm_token', $device->toArray());

        // Another user cannot remove my registration…
        $theirs = $this->login($this->user());
        $this->asApp($theirs)->deleteJson('/api/mobile/devices', ['fcm_token' => $long])->assertOk();
        $this->assertSame(1, MobileDevice::query()->count());
        // …and I can.
        $this->asApp($mine)->deleteJson('/api/mobile/devices', ['fcm_token' => $long])->assertOk();
        $this->assertSame(0, MobileDevice::query()->count());
    }

    public function test_device_registration_validates_and_needs_a_mobile_token(): void
    {
        $token = $this->login($this->me());
        $this->asApp($token)->postJson('/api/mobile/devices', ['fcm_token' => 'x', 'platform' => 'windows'])->assertStatus(422)->assertJsonValidationErrors('platform');
        $this->asApp($token)->postJson('/api/mobile/devices', ['fcm_token' => str_repeat('a', 4097), 'platform' => 'ios'])->assertStatus(422)->assertJsonValidationErrors('fcm_token');
        $this->asApp()->postJson('/api/mobile/devices', ['fcm_token' => 'x', 'platform' => 'ios'])->assertUnauthorized();
        $this->asWebsite();
        $this->actingAs($this->me())->postJson('/api/mobile/devices', ['fcm_token' => 'x', 'platform' => 'ios'])
            ->assertForbidden()->assertJsonPath('code', 'mobile_token_required');
    }
}
