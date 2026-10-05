<?php

namespace Tests\Feature;

use Database\Factories\UserFactory;
use PragmaRX\Google2FA\Google2FA;
use Tests\TestCase;

class MfaTest extends TestCase
{
    public function test_enrolment_needs_the_password_and_a_valid_code(): void
    {
        $user = $this->owner();
        $this->actingAs($user)->postJson('/api/auth/mfa/setup', ['password' => 'wrong'])->assertStatus(422);

        $setup = $this->actingAs($user)->postJson('/api/auth/mfa/setup', ['password' => UserFactory::PASSWORD])
            ->assertOk()->assertJsonStructure(['secret', 'otpauth_url', 'qr_svg']);
        $this->assertStringContainsString('<svg', $setup->json('qr_svg'));
        $this->assertFalse($user->fresh()->hasMfa(), 'not active until confirmed');

        $this->postJson('/api/auth/mfa/confirm', ['code' => '000000'])->assertStatus(422);
        $codes = $this->postJson('/api/auth/mfa/confirm', ['code' => (new Google2FA)->getCurrentOtp($setup->json('secret'))])
            ->assertOk()->json('recovery_codes');
        $this->assertCount(8, $codes);
        $user->refresh();
        $this->assertTrue($user->hasMfa());
        // Secrets are encrypted at rest and never serialised.
        $raw = \DB::table('users')->where('id', $user->id)->value('two_factor_secret');
        $this->assertNotSame($setup->json('secret'), $raw);
        $this->assertArrayNotHasKey('two_factor_secret', $user->toArray());
        $this->assertDatabaseHas('audit_logs', ['action' => 'auth.mfa.enabled', 'outcome' => 'success']);
    }

    public function test_turning_mfa_off_needs_password_and_code(): void
    {
        $user = $this->owner();
        $secret = $this->actingAs($user)->postJson('/api/auth/mfa/setup', ['password' => UserFactory::PASSWORD])->json('secret');
        $this->postJson('/api/auth/mfa/confirm', ['code' => (new Google2FA)->getCurrentOtp($secret)]);
        cache()->flush();

        $this->postJson('/api/auth/mfa/disable', ['password' => UserFactory::PASSWORD, 'code' => '000000'])->assertStatus(422);
        $this->assertTrue($user->fresh()->hasMfa());
        $this->postJson('/api/auth/mfa/disable', ['password' => UserFactory::PASSWORD, 'code' => (new Google2FA)->getCurrentOtp($secret)])->assertOk();
        $this->assertFalse($user->fresh()->hasMfa());
    }

    public function test_required_mfa_blocks_the_dashboard_until_enrolled(): void
    {
        config(['fx.mfa.required' => true]);
        $user = $this->owner();
        $this->actingAs($user)->getJson('/api/overview')->assertForbidden()->assertJsonPath('code', 'mfa_enrollment_required');
        $this->getJson('/api/auth/me')->assertOk()->assertJsonPath('user.mfa_required', true);
        $this->postJson('/api/auth/mfa/setup', ['password' => UserFactory::PASSWORD])->assertOk();
    }
}
