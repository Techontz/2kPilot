<?php

namespace Tests\Feature;

use App\Enums\AccountEnvironment;
use App\Enums\ConnectorType;
use App\Models\RiskProfile;
use App\Models\SystemState;
use App\Models\TradingAccount;
use App\Models\User;
use App\Models\UserTradingState;
use App\Services\Mfa\TwoFactorService;
use App\Services\Users\UserProvisioner;
use Database\Factories\UserFactory;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Http;
use PragmaRX\Google2FA\Google2FA;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class TradingControlTest extends TestCase
{
    use CreatesTradingData;

    private function stateOf(User $user): UserTradingState
    {
        return UserTradingState::query()->findOrFail($user->id);
    }

    public function test_a_new_user_starts_with_trading_stopped_in_demo(): void
    {
        $status = $this->actingAs($this->me())->getJson('/api/trading/status')->assertOk();
        $status->assertJson([
            'kill_switch_engaged' => true,
            'trading_mode' => 'DEMO',
            'live_trading_locked' => true,
            'live_authorized_at' => null,
            'platform_halted' => false,
            'engine_state' => 'offline',
            'new_orders_permitted' => false,
        ]);
    }

    public function test_stop_is_idempotent_audited_and_never_closes_positions(): void
    {
        Http::fake(); // any engine call would be recorded
        $me = $this->me();
        $this->actingAs($me)->postJson('/api/trading/resume', ['confirm' => true])->assertOk();
        $this->postJson('/api/trading/stop', ['reason' => 'news'])->assertOk()->assertJsonPath('kill_switch_engaged', true);
        $this->postJson('/api/trading/stop', ['reason' => 'again'])->assertOk();
        Http::assertNothingSent();
        $this->assertSame('news', $this->stateOf($me)->kill_switch_reason);
        $this->assertDatabaseCount('audit_logs', 3);
        $this->assertDatabaseHas('notifications', ['type' => 'trading.stopped', 'user_id' => $me->id]);
    }

    public function test_resume_needs_explicit_confirmation(): void
    {
        $this->actingAs($this->me())->postJson('/api/trading/resume')->assertStatus(422);
        $this->postJson('/api/trading/resume', ['confirm' => true])->assertOk()->assertJsonPath('kill_switch_engaged', false);
    }

    public function test_new_orders_are_permitted_only_with_a_running_engine(): void
    {
        $this->actingAs($this->me())->postJson('/api/trading/resume', ['confirm' => true]);
        $this->getJson('/api/trading/status')->assertJsonPath('new_orders_permitted', false);
        $this->engineAlive();
        $this->getJson('/api/trading/status')->assertJsonPath('engine_state', 'running')->assertJsonPath('new_orders_permitted', true);
    }

    public function test_one_users_stop_does_not_affect_another_user(): void
    {
        $alice = $this->user();
        $bob = $this->user();
        $this->engineAlive();
        $this->actingAs($alice)->postJson('/api/trading/resume', ['confirm' => true])->assertOk();
        $this->actingAs($bob)->postJson('/api/trading/resume', ['confirm' => true])->assertOk();
        $this->postJson('/api/trading/stop', ['reason' => 'bob stops'])->assertOk()->assertJsonPath('kill_switch_engaged', true);

        $this->assertFalse($this->stateOf($alice)->kill_switch_engaged);
        $this->assertTrue($this->stateOf($bob)->kill_switch_engaged);
        $this->actingAs($alice)->getJson('/api/trading/status')->assertJsonPath('new_orders_permitted', true);
    }

    public function test_mode_can_only_change_while_stopped(): void
    {
        config(['tradepilot.live_trading_enabled' => true]);
        $this->actingAs($this->me())->postJson('/api/trading/resume', ['confirm' => true]);
        $this->putJson('/api/trading/mode', ['mode' => 'LIVE'])->assertStatus(409)->assertJsonPath('code', 'stop_first');
        $this->putJson('/api/trading/mode', ['mode' => 'BACKTEST'])->assertStatus(422); // no such mode any more
    }

    public function test_live_is_impossible_while_the_server_lock_is_on(): void
    {
        $this->actingAs($this->me())
            ->putJson('/api/trading/mode', ['mode' => 'LIVE', 'password' => UserFactory::PASSWORD, 'confirmation_phrase' => 'ENABLE LIVE TRADING'])
            ->assertForbidden()->assertJsonPath('code', 'live_locked');
        $this->assertSame('DEMO', $this->stateOf($this->me())->trading_mode->value);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.mode.change_denied', 'outcome' => 'denied']);
    }

    public function test_live_needs_mfa_password_phrase_and_a_live_account_and_records_the_limits(): void
    {
        config(['tradepilot.live_trading_enabled' => true]);
        $me = $this->me();
        $live = $this->account(['environment' => AccountEnvironment::Live, 'risk_profile_id' => $this->defaultProfile()->id], ConnectorType::Deriv);
        $body = ['mode' => 'LIVE', 'password' => UserFactory::PASSWORD, 'confirmation_phrase' => 'ENABLE LIVE TRADING', 'account_id' => $live->id];
        $this->actingAs($me)->putJson('/api/trading/mode', $body)->assertForbidden()->assertJsonPath('code', 'mfa_required');

        $mfa = app(TwoFactorService::class);
        $secret = $mfa->begin($me)['secret'];
        $this->assertNotNull($mfa->confirm($me->fresh(), (new Google2FA)->getCurrentOtp($secret)));
        $me->refresh();
        // A fresh two-factor code is needed as well (each code works once: forget the last use between attempts).
        $otp = function () use ($me, $secret) {
            Cache::forget("mfa:last:{$me->id}");

            return (new Google2FA)->getCurrentOtp($secret);
        };
        $this->actingAs($me)->putJson('/api/trading/mode', $body)->assertForbidden()->assertJsonPath('code', 'mfa_code_invalid');
        $this->putJson('/api/trading/mode', ['mfa_code' => '000000'] + $body)->assertForbidden()->assertJsonPath('code', 'mfa_code_invalid');
        $this->putJson('/api/trading/mode', ['password' => 'wrong', 'mfa_code' => $otp()] + $body)->assertJsonPath('code', 'password_incorrect');
        $this->putJson('/api/trading/mode', ['confirmation_phrase' => 'yes', 'mfa_code' => $otp()] + $body)->assertJsonPath('code', 'confirmation_required');
        $demo = $this->account(['risk_profile_id' => $this->defaultProfile()->id]);
        $this->putJson('/api/trading/mode', ['account_id' => $demo->id, 'mfa_code' => $otp()] + $body)->assertStatus(422)->assertJsonPath('code', 'live_account_required');
        $theirs = $this->account(['environment' => AccountEnvironment::Live, 'risk_profile_id' => $this->defaultProfile($other = $this->user())->id], ConnectorType::Deriv, $other);
        $this->putJson('/api/trading/mode', ['account_id' => $theirs->id, 'mfa_code' => $otp()] + $body)->assertJsonPath('code', 'live_account_required');

        $this->putJson('/api/trading/mode', ['mfa_code' => $otp()] + $body)->assertOk()->assertJsonPath('trading_mode', 'LIVE');
        $state = $this->stateOf($me);
        $this->assertNotNull($state->live_authorized_at);
        $this->assertSame($live->id, $state->live_authorized_limits['account_id']);
        $this->assertSame($live->id, $state->live_authorized_account_id); // the engine trades only this account…
        $this->assertSame($live->risk_profile_id, $state->live_authorized_profile_id); // …under this profile
        $this->assertSame('Beginner', $state->live_authorized_limits['risk_profile_name']);
        $this->assertSame('2.000', $state->live_authorized_limits['limits']['max_daily_loss_pct']);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.mode.live_enabled']);

        $this->putJson('/api/trading/mode', ['mode' => 'DEMO'])->assertOk()->assertJsonPath('live_authorized_at', null);
        $this->assertNull($this->stateOf($me)->live_authorized_limits);
        $this->assertNull($this->stateOf($me)->live_authorized_account_id);
        $this->assertNull($this->stateOf($me)->live_authorized_profile_id);
    }

    public function test_a_used_two_factor_code_cannot_authorise_live_again(): void
    {
        config(['tradepilot.live_trading_enabled' => true]);
        $me = $this->me();
        $live = $this->account(['environment' => AccountEnvironment::Live, 'risk_profile_id' => $this->defaultProfile()->id], ConnectorType::Deriv);
        $mfa = app(TwoFactorService::class);
        $secret = $mfa->begin($me)['secret'];
        $code = (new Google2FA)->getCurrentOtp($secret);
        $mfa->confirm($me->fresh(), $code); // the enrolment used this code
        $body = ['mode' => 'LIVE', 'password' => UserFactory::PASSWORD, 'confirmation_phrase' => 'ENABLE LIVE TRADING', 'account_id' => $live->id, 'mfa_code' => $code];
        $this->actingAs($me->refresh())->putJson('/api/trading/mode', $body)->assertForbidden()->assertJsonPath('code', 'mfa_code_invalid');
        $this->assertSame('DEMO', $this->stateOf($me)->trading_mode->value);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.mode.change_denied', 'outcome' => 'denied']);
        // Switching back to DEMO never needs a code.
        $this->putJson('/api/trading/mode', ['mode' => 'DEMO'])->assertOk();
    }

    /** Put me in authorised LIVE mode on a LIVE Deriv account, trading running (as the mode switch would). */
    private function authorisedLive(?RiskProfile $profile = null, bool $accountEnabled = true): TradingAccount
    {
        config(['tradepilot.live_trading_enabled' => true]);
        $profile ??= $this->defaultProfile();
        $account = $this->account(['environment' => AccountEnvironment::Live, 'risk_profile_id' => $profile->id, 'trading_enabled' => $accountEnabled, 'label' => 'Real'], ConnectorType::Deriv);
        $this->stateOf($this->me())->forceFill([
            'trading_mode' => 'LIVE', 'kill_switch_engaged' => false, 'live_authorized_at' => now(),
            'live_authorized_limits' => ['account_id' => $account->id, 'risk_profile_id' => $profile->id, 'account_trading_enabled' => $accountEnabled],
            'live_authorized_account_id' => $account->id, 'live_authorized_profile_id' => $profile->id,
        ])->save();

        return $account;
    }

    private function assertLiveRevoked(string $because): void
    {
        $state = $this->stateOf($this->me());
        $this->assertSame('DEMO', $state->trading_mode->value);
        $this->assertTrue($state->kill_switch_engaged);
        $this->assertNull($state->live_authorized_at);
        $this->assertNull($state->live_authorized_account_id);
        $this->assertNull($state->live_authorized_profile_id);
        $this->assertStringStartsWith('Real-money authorization was revoked because', $state->live_revoked_reason);
        $this->assertStringContainsString($because, $state->live_revoked_reason);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.mode.live_revoked', 'target_id' => $this->me()->id]);
        $this->assertDatabaseHas('notifications', ['type' => 'trading.live_revoked', 'user_id' => $this->me()->id]);
        $this->actingAs($this->me())->getJson('/api/trading/status')
            ->assertJsonPath('trading_mode', 'DEMO')->assertJsonPath('live_revoked_reason', $state->live_revoked_reason);
    }

    private function assertStillLive(): void
    {
        $this->assertSame('LIVE', $this->stateOf($this->me())->trading_mode->value);
        $this->assertNotNull($this->stateOf($this->me())->live_authorized_at);
        $this->assertDatabaseMissing('audit_logs', ['action' => 'trading.mode.live_revoked']);
    }

    public function test_starting_in_live_mode_needs_a_fresh_live_confirmation(): void
    {
        $this->authorisedLive();
        $this->actingAs($this->me())->postJson('/api/trading/stop')->assertOk();
        // A dialog that still showed "Demo" sends no `live` flag: refused.
        $this->postJson('/api/trading/resume', ['confirm' => true])->assertStatus(409)->assertJsonPath('code', 'live_confirmation_required');
        $this->postJson('/api/trading/resume', ['confirm' => true, 'live' => false])->assertStatus(409);
        $this->assertTrue($this->stateOf($this->me())->kill_switch_engaged);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.kill_switch.release_denied']);
        $this->postJson('/api/trading/resume', ['confirm' => true, 'live' => true])->assertOk()
            ->assertJsonPath('kill_switch_engaged', false)->assertJsonPath('trading_mode', 'LIVE');
    }

    public function test_editing_the_authorised_risk_profile_revokes_live(): void
    {
        $profile = RiskProfile::query()->create(['user_id' => $this->me()->id, 'name' => 'Live limits'] + $this->defaultProfile()->only(array_keys(UserProvisioner::BEGINNER_LIMITS)));
        $this->authorisedLive($profile);
        $other = $this->defaultProfile();
        $body = fn (RiskProfile $p, array $change) => array_merge($p->only(array_keys(UserProvisioner::BEGINNER_LIMITS)), ['name' => $p->name], $change);
        // Another profile: LIVE stays.
        $this->actingAs($this->me())->putJson("/api/risk/profiles/{$other->id}", $body($other, ['max_daily_loss_pct' => 3]))->assertOk();
        $this->assertStillLive();
        $this->putJson("/api/risk/profiles/{$profile->id}", $body($profile, ['max_daily_loss_pct' => 5]))->assertOk();
        $this->assertLiveRevoked('the risk profile "Live limits" was edited');
    }

    public function test_changing_the_authorised_accounts_risk_profile_revokes_live(): void
    {
        $account = $this->authorisedLive();
        $profile = RiskProfile::query()->create(['user_id' => $this->me()->id, 'name' => 'Looser'] + $this->defaultProfile()->only(array_keys(UserProvisioner::BEGINNER_LIMITS)));
        $this->actingAs($this->me())->patchJson("/api/accounts/{$account->id}", ['label' => 'Renamed'])->assertOk();
        $this->assertStillLive();
        $this->patchJson("/api/accounts/{$account->id}", ['risk_profile_id' => $profile->id])->assertOk();
        $this->assertLiveRevoked('the risk profile of "Renamed" was changed');
    }

    public function test_switching_the_authorised_accounts_trading_off_and_on_again_revokes_live(): void
    {
        $account = $this->authorisedLive();
        $this->actingAs($this->me())->patchJson("/api/accounts/{$account->id}", ['trading_enabled' => false])->assertOk();
        $this->assertStillLive();
        $this->patchJson("/api/accounts/{$account->id}", ['trading_enabled' => true])->assertOk();
        $this->assertLiveRevoked('trading on "Real" was switched off and on again');
    }

    public function test_enabling_the_authorised_account_for_the_first_time_keeps_live(): void
    {
        $account = $this->authorisedLive(accountEnabled: false); // authorised first, then switched on: the normal order
        $this->actingAs($this->me())->patchJson("/api/accounts/{$account->id}", ['trading_enabled' => true])->assertOk();
        $this->assertStillLive();
        $this->patchJson("/api/accounts/{$account->id}", ['trading_enabled' => false])->assertOk();
        $this->patchJson("/api/accounts/{$account->id}", ['trading_enabled' => true])->assertOk();
        $this->assertLiveRevoked('switched off and on again');
    }

    public function test_adding_another_live_account_revokes_live(): void
    {
        $this->authorisedLive();
        $id = 'CR9000001';
        $this->fakeEngine([
            '/internal/connections/test' => [
                'account' => ['account_id' => $id, 'name' => 'Deriv real', 'server' => 'Deriv Options (real)', 'currency' => 'USD', 'environment' => 'LIVE',
                    'balance' => '50', 'equity' => '50', 'margin' => null, 'free_margin' => null, 'leverage' => null, 'trade_allowed' => true],
                'capabilities' => [], 'normalized_settings' => ['account_id' => $id], 'warnings' => [],
            ],
            '/internal/connections/' => ['status' => 'CONNECTED', 'detail' => 'Connected'],
        ]);
        $this->actingAs($this->me())->postJson('/api/brokers', [
            'connector_type' => 'deriv', 'expected_environment' => 'LIVE', 'acknowledge_live' => true, 'label' => 'Second real',
            'settings' => ['account_id' => $id], 'credentials' => ['token' => 'pat_x'], 'risk_profile_id' => $this->defaultProfile()->id,
        ])->assertCreated();
        $this->assertLiveRevoked('a new LIVE account "Second real" was added');
    }

    public function test_turning_mfa_off_revokes_live(): void
    {
        $me = $this->me();
        $mfa = app(TwoFactorService::class);
        $secret = $mfa->begin($me)['secret'];
        $mfa->confirm($me->fresh(), (new Google2FA)->getCurrentOtp($secret));
        Cache::forget("mfa:last:{$me->id}");
        $this->authorisedLive();
        $this->actingAs($me->fresh())->postJson('/api/auth/mfa/disable', ['password' => UserFactory::PASSWORD, 'code' => (new Google2FA)->getCurrentOtp($secret)])->assertOk();
        $this->assertLiveRevoked('two-factor authentication was turned off');
    }

    public function test_changing_the_password_revokes_live(): void
    {
        $this->authorisedLive();
        $new = 'An0ther-Secret-Pass';
        $this->actingAs($this->me())->putJson('/api/auth/password', ['current_password' => UserFactory::PASSWORD, 'password' => $new, 'password_confirmation' => $new])->assertOk();
        $this->assertLiveRevoked('your password was changed');
    }

    public function test_demo_users_are_untouched_by_revocation_triggers(): void
    {
        $new = 'An0ther-Secret-Pass';
        $this->actingAs($this->me())->putJson('/api/auth/password', ['current_password' => UserFactory::PASSWORD, 'password' => $new, 'password_confirmation' => $new])->assertOk();
        $this->assertDatabaseMissing('audit_logs', ['action' => 'trading.mode.live_revoked']);
        $this->assertNull($this->stateOf($this->me())->live_revoked_reason);
    }

    public function test_stop_still_works_when_the_api_budget_is_used_up(): void
    {
        config(['tradepilot.rate_limits.api_per_minute' => 2]);
        $this->actingAs($this->me())->postJson('/api/trading/resume', ['confirm' => true])->assertOk();
        $this->getJson('/api/trading/status')->assertOk();
        $this->getJson('/api/trading/status')->assertStatus(429);
        $this->postJson('/api/trading/stop', ['reason' => 'panic'])->assertOk()->assertJsonPath('kill_switch_engaged', true);
        $this->assertTrue($this->stateOf($this->me())->kill_switch_engaged);
    }

    public function test_the_live_confirmation_phrase_is_exposed(): void
    {
        $this->actingAs($this->me())->getJson('/api/trading/status')->assertJsonPath('live_confirmation_phrase', 'ENABLE LIVE TRADING');
    }

    public function test_close_positions_stops_trading_first_then_closes_only_my_accounts(): void
    {
        $this->fakeEngine(['/internal/positions/close-all' => ['closed' => 2, 'failed' => []]]);
        $me = $this->me();
        $mine = $this->account();
        $this->account([], ConnectorType::Paper, $this->user()); // someone else's
        $this->actingAs($me)->postJson('/api/trading/resume', ['confirm' => true]);
        $this->postJson('/api/trading/close-positions')->assertStatus(422); // confirmation required
        $this->postJson('/api/trading/close-positions', ['confirm' => true, 'reason' => 'panic'])
            ->assertOk()->assertJsonPath('closed', 2)->assertJsonPath('status.kill_switch_engaged', true);
        Http::assertSent(fn ($r) => str_ends_with($r->url(), '/internal/positions/close-all')
            && $r['actor_label'] === $me->email && $r['account_ids'] === [$mine->id]);
        $this->assertDatabaseHas('audit_logs', ['action' => 'trading.close_all_positions', 'outcome' => 'success']);
    }

    public function test_platform_halt_is_admin_only_and_overrides_every_user(): void
    {
        $this->engineAlive();
        $me = $this->me();
        $this->actingAs($me)->postJson('/api/trading/resume', ['confirm' => true]);
        $this->postJson('/api/admin/halt', ['reason' => 'nope'])->assertForbidden();
        $this->postJson('/api/admin/resume', ['confirm' => true])->assertForbidden();
        $this->assertFalse(SystemState::current()->kill_switch_engaged);

        $admin = $this->admin();
        $this->actingAs($admin)->postJson('/api/admin/halt')->assertStatus(422); // a reason is required
        $this->postJson('/api/admin/halt', ['reason' => 'exchange outage'])->assertOk()->assertJsonPath('platform_halted', true);
        $this->assertDatabaseHas('audit_logs', ['action' => 'platform.halt.engaged', 'actor_user_id' => $admin->id]);
        $this->assertDatabaseHas('notifications', ['type' => 'platform.halted', 'user_id' => null]);

        $this->actingAs($me)->getJson('/api/trading/status')
            ->assertJsonPath('platform_halted', true)->assertJsonPath('platform_halt_reason', 'exchange outage')
            ->assertJsonPath('kill_switch_engaged', false) // the user's own switch is untouched
            ->assertJsonPath('new_orders_permitted', false);

        $this->actingAs($admin)->postJson('/api/admin/resume', ['confirm' => true])->assertOk()->assertJsonPath('platform_halted', false);
        $this->actingAs($me)->getJson('/api/trading/status')->assertJsonPath('new_orders_permitted', true);
    }
}
