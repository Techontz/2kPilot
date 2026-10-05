<?php

namespace Tests\Feature;

use App\Models\AuditLog;
use App\Models\User;
use App\Services\Mfa\TwoFactorService;
use Database\Factories\UserFactory;
use PragmaRX\Google2FA\Google2FA;
use Tests\TestCase;

class AuthTest extends TestCase
{
    public function test_login_with_valid_credentials_starts_a_session(): void
    {
        $user = $this->owner(['email' => 'conrad@example.com']);

        $this->postJson('/api/auth/login', ['email' => 'Conrad@Example.com', 'password' => UserFactory::PASSWORD])
            ->assertOk()
            ->assertJsonPath('user.email', 'conrad@example.com')
            ->assertJsonPath('user.mfa_enabled', false);
        $this->assertAuthenticatedAs($user);
        $this->getJson('/api/auth/me')->assertOk()->assertJsonPath('user.role', 'owner');
        $this->assertNotNull($user->fresh()->last_login_at);
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.login', 'outcome' => 'success', 'actor_user_id' => $user->id]);
    }

    public function test_wrong_password_and_unknown_email_get_the_same_answer(): void
    {
        $this->owner(['email' => 'conrad@example.com']);

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
        $this->owner(['email' => 'conrad@example.com']);
        foreach (range(1, 5) as $_) {
            $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => 'wrong'])->assertStatus(422);
        }
        $this->postJson('/api/auth/login', ['email' => 'conrad@example.com', 'password' => UserFactory::PASSWORD])->assertStatus(429);
    }

    public function test_api_requires_authentication(): void
    {
        $this->getJson('/api/overview')->assertUnauthorized();
        $this->getJson('/api/brokers')->assertUnauthorized();
        $this->postJson('/api/trading/stop')->assertUnauthorized();
    }

    public function test_logout_ends_the_session(): void
    {
        $user = $this->owner();
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
        $user = $this->owner();
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

    /** @return array{0: User, 1: string} */
    private function userWithMfa(): array
    {
        $user = $this->owner();
        $service = app(TwoFactorService::class);
        $secret = $service->begin($user)['secret'];
        $service->confirm($user->fresh(), (new Google2FA)->getCurrentOtp($secret));
        cache()->flush(); // forget the enrolment code so the login code is accepted

        return [$user->fresh(), $secret];
    }
}
