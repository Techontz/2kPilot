<?php

namespace Tests\Feature;

use App\Models\User;
use Tests\TestCase;

class RegistrationTest extends TestCase
{
    private function body(array $overrides = []): array
    {
        return array_merge([
            'name' => 'Amina',
            'email' => 'Amina@Example.com',
            'password' => 'Trading-Pilot-42',
            'password_confirmation' => 'Trading-Pilot-42',
            'accept_terms' => true,
        ], $overrides);
    }

    public function test_sign_up_creates_a_provisioned_user_and_signs_in(): void
    {
        $this->postJson('/api/auth/register', $this->body())
            ->assertCreated()
            ->assertJsonPath('user.email', 'amina@example.com')
            ->assertJsonPath('user.role', 'user')
            ->assertJsonPath('user.mfa_enabled', false);
        $user = User::query()->where('email', 'amina@example.com')->firstOrFail();
        $this->assertAuthenticatedAs($user);
        $this->assertDatabaseHas('risk_profiles', ['user_id' => $user->id, 'name' => 'Beginner']);
        $this->assertDatabaseHas('user_trading_states', ['user_id' => $user->id, 'trading_mode' => 'DEMO', 'kill_switch_engaged' => true]);
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.registered', 'actor_user_id' => $user->id]);
        // A new sign-up waits for an admin: only auth/me answers.
        $this->getJson('/api/auth/me')->assertOk()->assertJsonPath('user.approved', false);
        $this->getJson('/api/trading/status')->assertForbidden()->assertJsonPath('code', 'approval_pending');
    }

    public function test_sign_up_without_approval_when_switched_off(): void
    {
        config(['tradepilot.registration_requires_approval' => false]);
        $this->postJson('/api/auth/register', $this->body())->assertCreated()->assertJsonPath('user.approved', true);
        $this->getJson('/api/trading/status')->assertOk()->assertJsonPath('kill_switch_engaged', true);
    }

    public function test_the_risk_disclosure_must_be_accepted(): void
    {
        $this->postJson('/api/auth/register', $this->body(['accept_terms' => false]))->assertJsonValidationErrors('accept_terms');
        $this->postJson('/api/auth/register', $this->body(['accept_terms' => null]))->assertJsonValidationErrors('accept_terms');
        $this->assertDatabaseCount('users', 0);
    }

    public function test_passwords_must_be_strong_and_confirmed(): void
    {
        foreach (['short-1A', 'alllowercase-42', 'NO-DIGITS-here'] as $weak) {
            $this->postJson('/api/auth/register', $this->body(['password' => $weak, 'password_confirmation' => $weak]))
                ->assertJsonValidationErrors('password');
        }
        $this->postJson('/api/auth/register', $this->body(['password_confirmation' => 'Something-Else-42']))->assertJsonValidationErrors('password');
        $this->assertGuest();
    }

    public function test_emails_are_unique_ignoring_case(): void
    {
        $this->user(['email' => 'amina@example.com']);
        $this->postJson('/api/auth/register', $this->body(['email' => 'AMINA@example.com']))->assertJsonValidationErrors('email');
    }

    public function test_a_taken_email_gets_a_generic_answer(): void
    {
        $this->user(['email' => 'amina@example.com']);
        $response = $this->postJson('/api/auth/register', $this->body(['email' => 'amina@example.com']))->assertStatus(422);
        $this->assertSame(["We couldn't create an account with these details."], $response->json('errors.email'));
        $this->assertStringNotContainsStringIgnoringCase('taken', $response->getContent());
        $this->assertStringNotContainsStringIgnoringCase('exists', $response->getContent());
    }

    public function test_sign_up_can_be_turned_off(): void
    {
        config(['tradepilot.registration_enabled' => false]);
        $this->postJson('/api/auth/register', $this->body())->assertForbidden()->assertJsonPath('code', 'registration_disabled');
        $this->assertDatabaseCount('users', 0);
    }

    public function test_sign_up_is_rate_limited(): void
    {
        foreach (range(1, 10) as $i) {
            $this->postJson('/api/auth/register', $this->body(['email' => "user{$i}@example.com"]));
            $this->postJson('/api/auth/logout');
        }
        $this->postJson('/api/auth/register', $this->body(['email' => 'late@example.com']))->assertStatus(429);
    }
}
