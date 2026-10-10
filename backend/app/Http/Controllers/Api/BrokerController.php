<?php

namespace App\Http\Controllers\Api;

use App\Enums\AccountEnvironment;
use App\Enums\AuditOutcome;
use App\Enums\ConnectorType;
use App\Exceptions\DomainException;
use App\Http\Controllers\Controller;
use App\Http\Resources\AccountResource;
use App\Models\BrokerConnection;
use App\Services\Audit\AuditLogger;
use App\Services\Brokers\BrokerService;
use App\Services\Brokers\DerivOAuth;
use App\Services\Engine\EngineException;
use App\Services\Security\BrokerVault;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\Validation\Rule;

/**
 * Brokers → Add Broker:
 *   1 choose broker · 2 demo/live · 3 authenticate · 4 test connection ·
 *   5 verify account · 6 risk profile · 7 finish.
 */
class BrokerController extends Controller
{
    private const DERIV_SESSION_KEY = 'deriv.oauth';

    public function __construct(
        private readonly BrokerService $brokers,
        private readonly DerivOAuth $oauth,
        private readonly BrokerVault $vault,
        private readonly AuditLogger $audit,
    ) {}

    public function connectors(): JsonResponse
    {
        return response()->json([
            'connectors' => $this->brokers->connectors($this->oauth),
            'vault_configured' => $this->vault->configured(),
            'deriv_signed_in' => session()->has(self::DERIV_SESSION_KEY),
        ]);
    }

    public function index(Request $request): JsonResponse
    {
        $this->authorize('viewAny', BrokerConnection::class);
        $connections = BrokerConnection::query()->ownedBy($request->user())->with(['accounts.riskProfile', 'accounts.assignments.strategy'])->orderBy('created_at')->get();

        return response()->json($connections->map(fn (BrokerConnection $c) => [
            'id' => $c->id,
            'label' => $c->label,
            'connector_type' => $c->connector_type->value,
            'broker' => config("brokers.{$c->connector_type->value}.name"),
            'expected_environment' => $c->expected_environment->value,
            'status' => $c->status->value,
            'status_detail' => $c->status_detail,
            'is_enabled' => $c->is_enabled,
            'has_credentials' => $c->credentials_encrypted !== null, // never the credentials themselves
            'settings' => $c->settings,
            'last_connected_at' => $c->last_connected_at?->toIso8601String(),
            'last_error_at' => $c->last_error_at?->toIso8601String(),
            'accounts' => AccountResource::collection($c->accounts),
        ]));
    }

    /** Step 4: Test connection (nothing is saved). */
    public function test(Request $request): JsonResponse
    {
        $this->authorize('create', BrokerConnection::class);
        [$type, $environment, $settings, $sealed] = $this->wizardInput($request);
        try {
            $result = $this->brokers->test($type, $environment, $settings, $sealed);
        } catch (EngineException $e) {
            $this->audit->record('broker.test', AuditOutcome::Failure, $request->user(), details: ['type' => $type->value, 'reason' => $e->getMessage()]);
            throw $e;
        }
        $this->audit->record('broker.test', actor: $request->user(), details: ['type' => $type->value, 'environment' => $result['account']['environment']]);

        return response()->json($result);
    }

    /** Step 7: Finish — test again, then save (trading disabled) and connect. */
    public function store(Request $request): JsonResponse
    {
        $this->authorize('create', BrokerConnection::class);
        $request->validate([
            'label' => ['nullable', 'string', 'max:120'],
            'risk_profile_id' => ['nullable', 'uuid'],
            'acknowledge_live' => ['boolean'],
        ]);
        [$type, $environment, $settings, $sealed] = $this->wizardInput($request);
        $account = $this->brokers->create(
            $request->user(), $type, $environment, (string) $request->input('label', ''), $settings, $sealed,
            $request->input('risk_profile_id'), (bool) $request->boolean('acknowledge_live'),
        );
        if ($type === ConnectorType::Deriv) {
            $request->session()->forget(self::DERIV_SESSION_KEY);
        }

        return response()->json(new AccountResource($account->load('connection', 'riskProfile')), 201);
    }

    public function reconnect(Request $request, BrokerConnection $connection): JsonResponse
    {
        $this->authorize('update', $connection);
        $result = $this->brokers->connect($connection, $request->user());

        return response()->json($result);
    }

    public function disconnect(Request $request, BrokerConnection $connection): JsonResponse
    {
        $this->authorize('update', $connection);
        $this->brokers->disconnect($connection, $request->user());

        return response()->json(['status' => 'DISCONNECTED']);
    }

    public function destroy(Request $request, BrokerConnection $connection): JsonResponse
    {
        $this->authorize('delete', $connection);

        return response()->json(['result' => $this->brokers->delete($connection, $request->user())]);
    }

    /** Deriv step 5: list the Options accounts reachable with the token. */
    public function derivAccounts(Request $request): JsonResponse
    {
        $this->authorize('create', BrokerConnection::class);
        $request->validate(['token' => ['nullable', 'string', 'max:500'], 'use_oauth' => ['boolean']]);
        [, $sealed] = $this->brokers->prepare(ConnectorType::Deriv, ['token' => (string) $request->input('token')], $this->oauthCredentials($request));

        return response()->json(['accounts' => $this->brokers->derivAccounts($sealed)]);
    }

    /** Deriv step 3 (option): start "Sign in with Deriv" (OAuth 2.0 + PKCE). */
    public function derivOAuthStart(Request $request): JsonResponse
    {
        $this->authorize('create', BrokerConnection::class);
        $start = $this->oauth->start();
        $request->session()->put('deriv.pkce', ['state' => $start['state'], 'verifier' => $start['verifier'], 'until' => now()->timestamp + 600]);

        return response()->json(['url' => $start['url']]);
    }

    /** Deriv redirects the browser here with ?code&state. */
    public function derivOAuthCallback(Request $request): RedirectResponse
    {
        $front = rtrim((string) config('tradepilot.frontend_url'), '/').'/settings/brokers/new';
        if (! $request->user()?->is_active) {
            return redirect()->away($front.'?deriv=signed_out');
        }
        $pkce = $request->session()->pull('deriv.pkce');
        if ($request->filled('error')) {
            return redirect()->away($front.'?deriv=cancelled');
        }
        if (! is_array($pkce) || ($pkce['until'] ?? 0) < now()->timestamp || ! hash_equals((string) $pkce['state'], (string) $request->query('state'))) {
            $this->audit->record('broker.deriv_oauth', AuditOutcome::Denied, $request->user(), details: ['reason' => 'state_mismatch']);

            return redirect()->away($front.'?deriv=invalid');
        }
        try {
            $tokens = $this->oauth->exchange((string) $request->query('code'), $pkce['verifier']);
        } catch (DomainException $e) {
            $this->audit->record('broker.deriv_oauth', AuditOutcome::Failure, $request->user(), details: ['reason' => $e->getMessage()]);

            return redirect()->away($front.'?deriv=failed');
        }
        // The token never reaches the browser: it is sealed and kept server-side.
        $request->session()->put(self::DERIV_SESSION_KEY, $this->vault->seal(array_filter([
            'token' => $tokens['access_token'],
            'token_kind' => 'oauth',
            'refresh_token' => $tokens['refresh_token'],
        ])));
        $this->audit->record('broker.deriv_oauth', actor: $request->user());

        return redirect()->away($front.'?deriv=connected');
    }

    /** @return array{0: ConnectorType, 1: AccountEnvironment, 2: array, 3: ?string} */
    private function wizardInput(Request $request): array
    {
        $data = $request->validate([
            'connector_type' => ['required', Rule::enum(ConnectorType::class)],
            'expected_environment' => ['required', Rule::enum(AccountEnvironment::class)->except([AccountEnvironment::Unknown])],
            'settings' => ['array'],
            'credentials' => ['array'],
            'credentials.*' => ['nullable', 'string', 'max:500'],
            'use_oauth' => ['boolean'],
        ]);
        $type = ConnectorType::from($data['connector_type']);
        $values = array_merge($data['settings'] ?? [], array_filter($data['credentials'] ?? [], fn ($v) => $v !== null && $v !== ''));
        [$settings, $sealed] = $this->brokers->prepare($type, $values, $type === ConnectorType::Deriv ? $this->oauthCredentials($request) : null, $request->user());

        return [$type, AccountEnvironment::from($data['expected_environment']), $settings, $sealed];
    }

    private function oauthCredentials(Request $request): ?array
    {
        if (! $request->boolean('use_oauth')) {
            return null;
        }
        $sealed = $request->session()->get(self::DERIV_SESSION_KEY);
        if (! is_string($sealed)) {
            throw new DomainException('Sign in with Deriv again — the sign-in has expired.', 422, 'deriv_signin_expired');
        }

        return $this->vault->open($sealed);
    }
}
