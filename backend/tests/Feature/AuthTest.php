<?php

namespace Tests\Feature;

use App\Models\AuditLog;
use App\Models\User;
use App\Providers\AppServiceProvider;
use App\Services\Mfa\TwoFactorService;
use Database\Factories\UserFactory;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\RateLimiter;
use PragmaRX\Google2FA\Google2FA;
use Tests\TestCase;

class AuthTest extends TestCase
{
    public function test_login_with_valid_credentials_starts_a_session(): void
    {
        $user = $this->user(['email' => 'conrad@example.com']);

        $this->postJson('/api/auth/login', ['email' => 'Conrad@Example.com', 'password' => UserFactory::PASSWORD])
            ->assertOk()
            ->assertJsonPath('user.email', 'conrad@example.com')
            ->assertJsonPath('user.mfa_enabled', false);
        $this->assertAuthenticatedAs($user);
        $this->getJson('/api/auth/me')->assertOk()->assertJsonPath('user.role', 'user');
        $this->assertNotNull($user->fresh()->last_login_at);
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.login', 'outcome' => 'success', 'actor_user_id' => $user->id]);
    }

    public function test_wrong_password_and_unknown_email_get_the_same_answer(): void
    {
        $this->user(['email' => 'conrad@example.com']);

        $wrong = $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => 'nope'])->assertStatus(422);
        $unknown = $this->postJson('/api/auth/login', ['email' => 'ghost@example.com', 'password' => 'nope'])->assertStatus(422);
        $this->assertSame($wrong->json('message'), $unknown->json('message'));
        $this->assertGuest();
        $this->assertSame(2, AuditLog::query()->where('action', 'auth.login')->where('outcome', 'failure')->count());
    }

    public function test_disabled_users_cannot_log_in(): void
    {
        $user = User::factory()->inactive()->create();
        $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertStatus(422);
        $this->assertGuest();
    }

    public function test_login_is_rate_limited(): void
    {
        $this->user(['email' => 'conrad@example.com']);
        foreach (range(1, 5) as $_) {
            $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => 'wrong'])->assertStatus(422);
        }
        $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => UserFactory::PASSWORD])->assertStatus(429);
    }

    public function test_successful_logins_do_not_use_up_attempts(): void
    {
        $this->user(['email' => 'conrad@example.com']);
        foreach (range(1, 8) as $_) {
            $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => UserFactory::PASSWORD])->assertOk();
        }
        foreach (range(1, 5) as $_) {
            $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => 'wrong'])->assertStatus(422);
        }
        $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => UserFactory::PASSWORD])->assertStatus(429);
    }

    public function test_the_login_limit_is_per_email_so_a_shared_ip_cannot_lock_everyone_out(): void
    {
        $this->user(['email' => 'conrad@example.com']);
        $this->user(['email' => 'amina@example.com']);
        foreach (range(1, 5) as $_) {
            $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => 'wrong'])->assertStatus(422);
        }
        $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => UserFactory::PASSWORD])->assertStatus(429);
        // Same IP, another account: still fine.
        $this->postJson('/api/auth/login', ['email' => 'amina@example.com', 'password' => UserFactory::PASSWORD])->assertOk();
    }

    public function test_the_login_limit_also_caps_one_ip_across_many_emails(): void
    {
        config(['tradepilot.login_attempts_per_ip' => 3]);
        foreach (range(1, 3) as $i) {
            $this->postJson('/api/auth/login', ['email' => "ghost{$i}@example.com", 'password' => 'wrong'])->assertStatus(422);
        }
        $this->postJson('/api/auth/login', ['email' => 'ghost9@example.com', 'password' => 'wrong'])->assertStatus(429);
        $this->withServerVariables(['REMOTE_ADDR' => '10.0.0.9'])
            ->postJson('/api/auth/login', ['email' => 'ghost9@example.com', 'password' => 'wrong'])->assertStatus(422);
    }

    public function test_a_correct_password_waiting_for_mfa_counts_toward_the_login_limit(): void
    {
        [$user] = $this->userWithMfa();
        foreach (range(1, 5) as $_) {
            $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertOk()->assertJson(['mfa_required' => true]);
        }
        $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertStatus(429);
    }

    public function test_unknown_emails_still_cost_a_password_hash_check(): void
    {
        Hash::spy()->shouldReceive('make')->andReturn('$2y$04$not-a-real-hash');
        $this->postJson('/api/auth/login', ['email' => 'ghost@example.com', 'password' => 'nope'])->assertStatus(422);
        Hash::shouldHaveReceived('check')->once();
    }

    public function test_a_new_session_does_not_reset_the_mfa_code_limit(): void
    {
        [$user, $secret] = $this->userWithMfa();
        foreach (range(1, 5) as $_) { // a fresh session (new cookie) for every try, as an attacker would
            $this->flushSession();
            $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertJson(['mfa_required' => true]);
            $this->postJson('/api/auth/mfa', ['code' => ''])->assertStatus(422); // each try uses up the code step's budget
            RateLimiter::clear(md5('login'.AppServiceProvider::loginKey($user->email))); // only the code step is under test here
        }
        $this->flushSession();
        $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertJson(['mfa_required' => true]);
        $this->postJson('/api/auth/mfa', ['code' => (new Google2FA)->getCurrentOtp($secret)])->assertStatus(429);
        $this->assertGuest();
    }

    public function test_repeated_wrong_codes_lock_the_users_code_step(): void
    {
        [$user, $secret] = $this->userWithMfa();
        $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertJson(['mfa_required' => true]);
        foreach (range(1, 4) as $i) { // a new IP each time: the per-IP limit is not what stops this
            $this->withServerVariables(['REMOTE_ADDR' => "10.0.1.{$i}"])
                ->postJson('/api/auth/mfa', ['code' => '000000'])->assertStatus(422)->assertJsonPath('code', 'invalid_code');
        }
        $this->withServerVariables(['REMOTE_ADDR' => '10.0.1.5'])
            ->postJson('/api/auth/mfa', ['code' => '000000'])->assertStatus(429)->assertJsonPath('code', 'mfa_locked');
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.mfa.locked', 'outcome' => 'denied', 'target_id' => $user->id]);

        // The pending sign-in is gone, and even a right code after a new password step is refused for 15 minutes.
        $this->withServerVariables(['REMOTE_ADDR' => '10.0.1.6'])
            ->postJson('/api/auth/mfa', ['code' => (new Google2FA)->getCurrentOtp($secret)])->assertStatus(422)->assertJsonPath('code', 'mfa_expired');
        $this->withServerVariables(['REMOTE_ADDR' => '10.0.1.7'])
            ->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertJson(['mfa_required' => true]);
        $this->withServerVariables(['REMOTE_ADDR' => '10.0.1.8'])
            ->postJson('/api/auth/mfa', ['code' => (new Google2FA)->getCurrentOtp($secret)])->assertStatus(429)->assertJsonPath('code', 'mfa_locked');
        $this->assertGuest();

        $this->travel(16)->minutes();
        $this->withServerVariables(['REMOTE_ADDR' => '10.0.1.9'])
            ->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertJson(['mfa_required' => true]);
        $this->withServerVariables(['REMOTE_ADDR' => '10.0.1.9'])
            ->postJson('/api/auth/mfa', ['code' => (new Google2FA)->getCurrentOtp($secret)])->assertOk();
        $this->assertAuthenticatedAs($user);
    }

    public function test_api_requires_authentication(): void
    {
        $this->getJson('/api/overview')->assertUnauthorized();
        $this->getJson('/api/brokers')->assertUnauthorized();
        $this->postJson('/api/trading/stop')->assertUnauthorized();
    }

    public function test_logout_ends_the_session(): void
    {
        $user = $this->me();
        $this->actingAs($user)->postJson('/api/auth/logout')->assertOk();
        $this->assertGuest('web');
    }

    public function test_mfa_login_requires_a_valid_code_before_the_session_exists(): void
    {
        [$user, $secret] = $this->userWithMfa();

        $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])
            ->assertOk()->assertJson(['mfa_required' => true]);
        $this->assertGuest();
        $this->getJson('/api/auth/me')->assertUnauthorized();

        $this->postJson('/api/auth/mfa', ['code' => '000000'])->assertStatus(422)->assertJsonPath('code', 'invalid_code');
        $this->assertGuest();

        $code = (new Google2FA)->getCurrentOtp($secret);
        $this->postJson('/api/auth/mfa', ['code' => $code])->assertOk()->assertJsonPath('user.mfa_enabled', true);
        $this->assertAuthenticatedAs($user);
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.login', 'outcome' => 'success']);
    }

    public function test_a_totp_code_cannot_be_replayed(): void
    {
        [$user, $secret] = $this->userWithMfa();
        $code = (new Google2FA)->getCurrentOtp($secret);
        $service = app(TwoFactorService::class);
        $this->assertTrue($service->verify($user, $code));
        $this->assertFalse($service->verify($user, $code));
    }

    public function test_recovery_codes_work_once(): void
    {
        $user = $this->me();
        $service = app(TwoFactorService::class);
        $secret = $service->begin($user)['secret'];
        $codes = $service->confirm($user->fresh(), (new Google2FA)->getCurrentOtp($secret));
        $this->assertCount(8, $codes);

        $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD])->assertJson(['mfa_required' => true]);
        $this->postJson('/api/auth/mfa', ['code' => strtolower($codes[0])])->assertOk();
        $this->postJson('/api/auth/logout');

        $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD]);
        $this->postJson('/api/auth/mfa', ['code' => $codes[0]])->assertStatus(422);
    }

    public function test_pending_mfa_login_expires(): void
    {
        [$user] = $this->userWithMfa();
        $this->postJson('/api/auth/login', ['email' => $user->email, 'password' => UserFactory::PASSWORD]);
        $this->travel(6)->minutes();
        $this->postJson('/api/auth/mfa', ['code' => '123456'])->assertStatus(422)->assertJsonPath('code', 'mfa_expired');
    }

    public function test_change_password_keeps_the_user_signed_in(): void
    {
        $user = $this->me();
        $new = 'An0ther-Secret-Pass';
        $this->actingAs($user)->putJson('/api/auth/password', [
            'current_password' => UserFactory::PASSWORD, 'password' => $new, 'password_confirmation' => $new,
        ])->assertOk()->assertJsonPath('ok', true);
        $this->assertTrue(Hash::check($new, $user->fresh()->password));
        $this->getJson('/api/auth/me')->assertOk();
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.password_changed', 'outcome' => 'success', 'actor_user_id' => $user->id]);
        $this->assertDatabaseHas('notifications', ['type' => 'security.password', 'user_id' => $user->id]);
    }

    public function test_change_password_needs_the_current_password(): void
    {
        $user = $this->me();
        $this->actingAs($user)->putJson('/api/auth/password', [
            'current_password' => 'not-it', 'password' => 'An0ther-Secret-Pass', 'password_confirmation' => 'An0ther-Secret-Pass',
        ])->assertStatus(422)->assertJsonPath('code', 'password_incorrect')->assertJsonPath('message', 'Your current password is incorrect.');
        $this->assertTrue(Hash::check(UserFactory::PASSWORD, $user->fresh()->password));
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.password_changed', 'outcome' => 'denied']);
    }

    public function test_change_password_rejects_weak_unconfirmed_or_unchanged_passwords(): void
    {
        $this->actingAs($this->me());
        $this->putJson('/api/auth/password', ['current_password' => UserFactory::PASSWORD, 'password' => 'short', 'password_confirmation' => 'short'])
            ->assertJsonValidationErrors('password');
        $this->putJson('/api/auth/password', ['current_password' => UserFactory::PASSWORD, 'password' => 'An0ther-Secret-Pass', 'password_confirmation' => 'different'])
            ->assertJsonValidationErrors('password');
        $this->putJson('/api/auth/password', ['current_password' => UserFactory::PASSWORD, 'password' => UserFactory::PASSWORD, 'password_confirmation' => UserFactory::PASSWORD])
            ->assertJsonValidationErrors('password');
        $this->assertTrue(Hash::check(UserFactory::PASSWORD, $this->me()->fresh()->password));
    }

    public function test_change_password_requires_authentication(): void
    {
        $this->putJson('/api/auth/password', ['current_password' => 'x', 'password' => 'y', 'password_confirmation' => 'y'])->assertUnauthorized();
    }

    /** @return array{0: User, 1: string} */
    private function userWithMfa(): array
    {
        $user = $this->me();
        $service = app(TwoFactorService::class);
        $secret = $service->begin($user)['secret'];
        $service->confirm($user->fresh(), (new Google2FA)->getCurrentOtp($secret));
        cache()->flush(); // forget the enrolment code so the login code is accepted

        return [$user->fresh(), $secret];
    }
}
