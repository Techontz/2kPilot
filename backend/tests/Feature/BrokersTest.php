<?php

namespace Tests\Feature;

use App\Enums\AccountEnvironment;
use App\Enums\ConnectorType;
use App\Models\BrokerConnection;
use App\Models\TradingAccount;
use App\Services\Brokers\DerivOAuth;
use App\Services\Security\BrokerVault;
use Illuminate\Http\Client\Request;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\Http;
use Tests\Support\CreatesTradingData;
use Tests\TestCase;

class BrokersTest extends TestCase
{
    use CreatesTradingData;

    private function engineAccount(string $environment = 'DEMO', string $id = 'DOT90004580'): array
    {
        return [
            'account' => ['account_id' => $id, 'name' => "Deriv DEMO {$id}", 'server' => 'Deriv Options (demo)', 'currency' => 'USD',
                'environment' => $environment, 'balance' => '10000', 'equity' => '10000', 'margin' => null, 'free_margin' => null, 'leverage' => null, 'trade_allowed' => true],
            'symbol_count' => 89,
            'categories' => ['forex' => 30, 'synthetic' => 40],
            'capabilities' => ['pending_orders' => false, 'volume_unit' => 'lots', 'notes' => ['multipliers']],
            'normalized_settings' => ['account_id' => $id, 'multiplier' => null],
            'warnings' => [],
        ];
    }

    private function derivBody(array $extra = []): array
    {
        return array_merge([
            'connector_type' => 'deriv',
            'expected_environment' => 'DEMO',
            'settings' => ['account_id' => 'DOT90004580'],
            'credentials' => ['token' => 'pat_super_secret_token'],
            'risk_profile_id' => $this->defaultProfile()->id,
        ], $extra);
    }

    public function test_catalogue_lists_paper_and_deriv(): void
    {
        $body = $this->actingAs($this->me())->getJson('/api/brokers/connectors')->assertOk()->json();
        $connectors = collect($body['connectors'])->keyBy('id');
        $this->assertSame(['paper', 'deriv'], $connectors->keys()->all());
        $this->assertSame('needs_setup', $connectors['deriv']['status']); // no DERIV_APP_ID in tests
        $this->assertSame(['pat'], $connectors['deriv']['auth_methods']); // OAuth hidden until configured
        $this->assertSame(['DEMO', 'LIVE'], $connectors['deriv']['environments']);
        $this->assertTrue($body['vault_configured']);
    }

    public function test_connection_test_sends_only_encrypted_credentials_to_the_engine(): void
    {
        $this->fakeEngine(['/internal/connections/test' => $this->engineAccount()]);
        $this->actingAs($this->me())->postJson('/api/brokers/test', $this->derivBody())
            ->assertOk()->assertJsonPath('account.environment', 'DEMO')->assertJsonPath('symbol_count', 89);
        Http::assertSent(function (Request $request) {
            $this->assertStringNotContainsString('pat_super_secret_token', $request->body());
            $sealed = $request['credentials_encrypted'];
            $this->assertSame(['token' => 'pat_super_secret_token', 'token_kind' => 'pat'], app(BrokerVault::class)->open($sealed));

            return $request['settings']['account_id'] === 'DOT90004580' && $request->hasHeader('X-Engine-Signature');
        });
        $this->assertDatabaseCount('broker_connections', 0); // testing never saves
    }

    public function test_finish_saves_the_account_disabled_with_secrets_encrypted(): void
    {
        $this->fakeEngine([
            '/internal/connections/test' => $this->engineAccount(),
            '/internal/connections/' => ['status' => 'CONNECTED', 'detail' => 'Connected', 'symbols' => 89],
        ]);
        $response = $this->actingAs($this->me())->postJson('/api/brokers', $this->derivBody(['label' => 'My Deriv demo']))
            ->assertCreated()
            ->assertJsonPath('environment', 'DEMO')
            ->assertJsonPath('trading_enabled', false)
            ->assertJsonPath('broker', 'Deriv')
            ->assertJsonPath('risk_profile.name', 'Beginner');
        $this->assertStringNotContainsString('pat_super_secret_token', $response->getContent());
        $this->assertStringNotContainsString('credentials', $response->getContent());
        $connection = BrokerConnection::query()->firstOrFail();
        $this->assertSame($this->me()->id, $connection->user_id);
        $this->assertSame($this->me()->id, TradingAccount::query()->firstOrFail()->user_id);
        $this->assertStringNotContainsString('pat_super_secret_token', $connection->getRawOriginal('credentials_encrypted'));
        $this->assertSame('pat_super_secret_token', app(BrokerVault::class)->open($connection->credentials_encrypted)['token']);
        $this->assertStringNotContainsString('pat_super_secret_token', json_encode(\DB::table('audit_logs')->get()));
        $listing = $this->getJson('/api/brokers')->assertOk();
        $this->assertStringNotContainsString('pat_super_secret_token', $listing->getContent());
        $listing->assertJsonPath('0.has_credentials', true);
        Http::assertSent(fn (Request $r) => str_contains($r->url(), "/internal/connections/{$connection->id}/connect"));
    }

    public function test_environment_mismatch_from_the_engine_saves_nothing(): void
    {
        $this->fakeEngine(['/internal/connections/test' => Http::response(['error' => ['code' => 'environment_mismatch',
            'message' => 'You selected DEMO, but the broker reports a LIVE account. Nothing was saved.']], 422)]);
        $this->actingAs($this->me())->postJson('/api/brokers', $this->derivBody())
            ->assertStatus(422)->assertJsonPath('code', 'environment_mismatch');
        $this->assertDatabaseCount('broker_connections', 0);
        $this->assertDatabaseHas('audit_logs', ['action' => 'broker.add_failed', 'outcome' => 'failure']);
    }

    public function test_live_accounts_need_explicit_acknowledgement(): void
    {
        Http::fake();
        $this->actingAs($this->me())->postJson('/api/brokers', $this->derivBody(['expected_environment' => 'LIVE']))
            ->assertForbidden()->assertJsonPath('code', 'live_ack_required');
        Http::assertNothingSent();
    }

    public function test_the_same_broker_account_cannot_be_added_twice(): void
    {
        $this->account(['broker_account_id' => 'DOT90004580', 'server' => 'Deriv Options (demo)'], ConnectorType::Deriv);
        $this->fakeEngine(['/internal/connections/test' => $this->engineAccount()]);
        $this->actingAs($this->me())->postJson('/api/brokers', $this->derivBody())->assertStatus(409);
    }

    public function test_engine_offline_is_a_clear_error(): void
    {
        $this->engineDown();
        $this->actingAs($this->me())->postJson('/api/brokers/test', $this->derivBody())
            ->assertStatus(503)->assertJsonPath('code', 'engine_unreachable');
    }

    public function test_enabling_trading_needs_a_risk_profile_and_respects_the_live_lock(): void
    {
        $owner = $this->me();
        $account = $this->account();
        $this->actingAs($owner)->patchJson("/api/accounts/{$account->id}", ['trading_enabled' => true])
            ->assertForbidden()->assertJsonFragment(['message' => 'Assign a risk profile before enabling trading.']);
        $this->patchJson("/api/accounts/{$account->id}", ['risk_profile_id' => $this->defaultProfile()->id, 'trading_enabled' => true])
            ->assertOk()->assertJsonPath('trading_enabled', true);

        $live = $this->account(['environment' => AccountEnvironment::Live, 'risk_profile_id' => $this->defaultProfile()->id], ConnectorType::Deriv);
        $this->patchJson("/api/accounts/{$live->id}", ['trading_enabled' => true])->assertForbidden()
            ->assertJsonFragment(['message' => 'LIVE trading is locked on this server (LIVE_TRADING_ENABLED=false).']);
        $this->assertDatabaseHas('audit_logs', ['action' => 'account.trading_enable_denied', 'outcome' => 'denied']);
    }

    public function test_removing_the_risk_profile_turns_trading_off(): void
    {
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id, 'trading_enabled' => true]);
        $this->actingAs($this->me())->patchJson("/api/accounts/{$account->id}", ['risk_profile_id' => null])
            ->assertOk()->assertJsonPath('trading_enabled', false);
    }

    public function test_disconnect_and_reconnect(): void
    {
        $this->fakeEngine([
            '/internal/connections/' => fn (Request $r) => Http::response(str_ends_with($r->url(), '/disconnect')
                ? ['status' => 'DISCONNECTED'] : ['status' => 'CONNECTED', 'detail' => 'Connected', 'symbols' => 3]),
        ]);
        $account = $this->account(['trading_enabled' => true, 'risk_profile_id' => $this->defaultProfile()->id], ConnectorType::Deriv);
        $owner = $this->me();
        $this->actingAs($owner)->postJson("/api/brokers/{$account->connection_id}/disconnect")->assertOk();
        $connection = $account->connection->fresh();
        $this->assertFalse($connection->is_enabled);
        $this->assertSame('DISCONNECTED', $connection->status->value);
        $this->assertFalse($account->fresh()->trading_enabled);
        $this->postJson("/api/brokers/{$account->connection_id}/reconnect")->assertOk()->assertJsonPath('status', 'CONNECTED');
        $this->assertTrue($connection->fresh()->is_enabled);
    }

    public function test_removing_a_broker_with_history_archives_it_and_wipes_secrets(): void
    {
        Http::fake(['engine.test/*' => Http::response(['status' => 'DISCONNECTED'])]);
        $account = $this->account([], ConnectorType::Deriv);
        $this->closedTrade($account, 12.5);
        $this->actingAs($this->me())->deleteJson("/api/brokers/{$account->connection_id}")
            ->assertOk()->assertJsonPath('result', 'broker.archived');
        $connection = BrokerConnection::query()->findOrFail($account->connection_id);
        $this->assertNull($connection->credentials_encrypted);
        $this->assertFalse($connection->is_enabled);
        $this->assertDatabaseCount('trades', 1);
    }

    public function test_open_positions_block_removal(): void
    {
        $account = $this->account([], ConnectorType::Deriv);
        $this->openTrade($account);
        $this->actingAs($this->me())->deleteJson("/api/brokers/{$account->connection_id}")->assertStatus(409);
    }

    public function test_deriv_oauth_uses_pkce_and_keeps_the_token_server_side(): void
    {
        config(['tradepilot.deriv.app_id' => 'app12345', 'tradepilot.deriv.oauth_redirect_url' => 'http://localhost:3421/api/brokers/deriv/oauth/callback']);
        $owner = $this->me();
        $url = $this->actingAs($owner)->postJson('/api/brokers/deriv/oauth/start')->assertOk()->json('url');
        parse_str(parse_url($url, PHP_URL_QUERY), $query);
        $this->assertStringStartsWith('https://auth.deriv.com/oauth2/auth', $url);
        $this->assertSame(['code', 'app12345', 'S256', 'trade'], [$query['response_type'], $query['client_id'], $query['code_challenge_method'], $query['scope']]);
        // Deriv's firewall blocks loopback redirect URLs: Deriv uses the app's registered one instead.
        $this->assertArrayNotHasKey('redirect_uri', $query);
        $pkce = session('deriv.pkce');
        $this->assertSame(rtrim(strtr(base64_encode(hash('sha256', $pkce['verifier'], true)), '+/', '-_'), '='), $query['code_challenge']);

        $this->get('/api/brokers/deriv/oauth/callback?code=abc&state=forged')->assertRedirect('http://localhost:3421/settings/brokers/new?deriv=invalid');

        $this->withSession(['deriv.pkce' => $pkce]);
        Http::fake([
            'auth.deriv.com/oauth2/token' => Http::response(['access_token' => 'ory_at_secret', 'expires_in' => 3600, 'token_type' => 'Bearer']),
            'engine.test/internal/deriv/accounts*' => Http::response([['account_id' => 'DOT90004580', 'account_type' => 'demo', 'currency' => 'USD', 'balance' => '10000', 'status' => 'active']]),
        ]);
        $this->get("/api/brokers/deriv/oauth/callback?code=abc&state={$pkce['state']}")->assertRedirect('http://localhost:3421/settings/brokers/new?deriv=connected');
        Http::assertSent(fn (Request $r) => str_contains($r->url(), 'oauth2/token') && $r['code_verifier'] === $pkce['verifier'] && $r['grant_type'] === 'authorization_code'
            && ! array_key_exists('redirect_uri', $r->data()));
        $this->assertStringNotContainsString('ory_at_secret', (string) session('deriv.oauth'));

        $this->postJson('/api/brokers/deriv/accounts', ['use_oauth' => true])->assertOk()->assertJsonPath('accounts.0.account_type', 'demo');
        Http::assertSent(fn (Request $r) => str_contains($r->url(), '/internal/deriv/accounts')
            && app(BrokerVault::class)->open($r['credentials_encrypted']) === ['token' => 'ory_at_secret', 'token_kind' => 'oauth']);
    }

    public function test_deriv_oauth_sends_a_public_redirect_url(): void
    {
        $redirect = 'https://app.example.com/api/brokers/deriv/oauth/callback';
        config(['tradepilot.deriv.app_id' => 'app12345', 'tradepilot.deriv.oauth_redirect_url' => $redirect]);
        $url = $this->actingAs($this->me())->postJson('/api/brokers/deriv/oauth/start')->assertOk()->json('url');
        parse_str(parse_url($url, PHP_URL_QUERY), $query);
        $this->assertSame($redirect, $query['redirect_uri']);

        $pkce = session('deriv.pkce');
        Http::fake(['auth.deriv.com/oauth2/token' => Http::response(['access_token' => 'ory_at_x', 'expires_in' => 3600])]);
        $this->get("/api/brokers/deriv/oauth/callback?code=abc&state={$pkce['state']}");
        Http::assertSent(fn (Request $r) => str_contains($r->url(), 'oauth2/token') && $r['redirect_uri'] === $redirect);
    }

    public function test_deriv_oauth_return_uses_the_session_whatever_the_referer(): void
    {
        // Deriv's redirect is a top-level navigation whose Referer is auth.deriv.com:
        // the callback must still find the signed-in user in the session cookie.
        config(['tradepilot.deriv.app_id' => 'app12345', 'tradepilot.deriv.oauth_redirect_url' => 'http://localhost:3421/api/brokers/deriv/oauth/callback']);
        $owner = $this->me();
        $this->app['auth']->forgetGuards();
        $this->withSession([Auth::guard('web')->getName() => $owner->id, 'deriv.pkce' => ['state' => 'state-123456', 'verifier' => str_repeat('v', 64), 'until' => now()->addMinutes(5)->timestamp]]);
        Http::fake(['auth.deriv.com/oauth2/token' => Http::response(['access_token' => 'ory_at_x', 'expires_in' => 3600])]);

        $this->withHeader('Referer', 'https://auth.deriv.com/')
            ->get('/api/brokers/deriv/oauth/callback?code=abc&state=state-123456')
            ->assertRedirect('http://localhost:3421/settings/brokers/new?deriv=connected');
    }

    public function test_deriv_oauth_return_without_a_session_goes_back_to_the_dashboard(): void
    {
        $this->withHeader('Referer', 'https://auth.deriv.com/')
            ->get('/api/brokers/deriv/oauth/callback?code=abc&state=x')
            ->assertRedirect(rtrim((string) config('tradepilot.frontend_url'), '/').'/settings/brokers/new?deriv=signed_out');
    }

    public function test_loopback_redirect_urls_are_detected(): void
    {
        foreach (['http://localhost:3001/cb', 'https://localhost/cb', 'http://127.0.0.1:3421/cb', 'http://[::1]:3000/cb', 'http://app.localhost/cb'] as $url) {
            $this->assertTrue(DerivOAuth::isLoopback($url), $url);
        }
        foreach (['https://app.example.com/cb', 'http://localhost.example.com/cb', 'http://10.0.0.5/cb'] as $url) {
            $this->assertFalse(DerivOAuth::isLoopback($url), $url);
        }
    }

    public function test_account_list_shows_card_fields(): void
    {
        $account = $this->account(['risk_profile_id' => $this->defaultProfile()->id]);
        $this->actingAs($this->me())->getJson('/api/accounts')->assertOk()
            ->assertJsonPath('0.id', $account->id)
            ->assertJsonPath('0.environment', 'PAPER')
            ->assertJsonPath('0.connection_status', 'CONNECTED')
            ->assertJsonPath('0.broker', 'Paper Trading')
            ->assertJsonStructure([['balance', 'equity', 'currency', 'active_strategies', 'trading_enabled', 'synced_at', 'capabilities']]);
        $this->assertSame(1, TradingAccount::query()->count());
    }
}
