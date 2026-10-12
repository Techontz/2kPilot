<?php

namespace App\Providers;

use App\Models\User;
use App\Services\Engine\EngineClient;
use App\Services\Mobile\MobileMfaChallenges;
use App\Services\Security\BrokerVault;
use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Gate;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\ServiceProvider;
use Illuminate\Validation\Rules\Password;

class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->singleton(EngineClient::class, fn () => new EngineClient(
            config('tradepilot.engine.url'),
            config('tradepilot.engine.secret'),
            (int) config('tradepilot.engine.timeout'),
        ));
        $this->app->singleton(BrokerVault::class, fn () => new BrokerVault(config('tradepilot.broker_credentials_key')));
    }

    public function boot(): void
    {
        // created_at / updated_at as DATETIME(6) in UTC — the precision the
        // trading engine reads and writes.
        Blueprint::macro('utcTimestamps', function () {
            /** @var Blueprint $this */
            $this->dateTime('created_at', 6)->useCurrent();
            $this->dateTime('updated_at', 6)->useCurrent()->useCurrentOnUpdate();
        });

        // Platform halt / resume (stops every user's trading): admins only.
        Gate::define('operate-platform', fn (User $user) => $user->is_active && $user->isAdmin());

        // Sign-up passwords: at least 10 characters, mixed case and a number.
        // (Not checked against breach lists: that needs an outside service.)
        Password::defaults(fn () => Password::min(10)->mixedCase()->numbers());

        $this->configureRateLimits();
    }

    /** The per-email login limiter key (cleared after a completed MFA sign-in). */
    public static function loginKey(string $email): string
    {
        return 'login:'.strtolower(trim($email));
    }

    private function configureRateLimits(): void
    {
        RateLimiter::for('api', fn (Request $request) => Limit::perMinute((int) config('tradepilot.rate_limits.api_per_minute', 300))->by($request->user()?->id ?: $request->ip()));

        // Login: per email first, so one shared proxy/office IP cannot lock everyone
        // out; per IP as a looser second cap. Failed attempts count, and so does a
        // correct password that only reached the MFA step (it still guesses the
        // password); a completed sign-in never counts.
        $attempts = (int) config('tradepilot.login_attempts', 5);
        $counts = fn ($response) => $response->getStatusCode() >= 400
            || ($response instanceof JsonResponse && ($response->getData(true)['mfa_required'] ?? false) === true);
        RateLimiter::for('login', fn (Request $request) => [
            Limit::perMinutes(15, $attempts)->by(self::loginKey((string) $request->input('email')))->after($counts),
            Limit::perMinutes(15, (int) config('tradepilot.login_attempts_per_ip', 50))->by('login-ip:'.$request->ip())->after($counts),
        ]);
        // Per IP: sign-up has no account to key on yet (behind a proxy, see TRUSTED_PROXIES).
        RateLimiter::for('register', fn (Request $request) => Limit::perHour(10)->by('register:'.$request->ip()));
        RateLimiter::for('password', fn (Request $request) => Limit::perMinute(5)->by('password:'.$request->user()?->id));
        // The live-updates stream reconnects about once a minute per open tab (and on every full page load).
        RateLimiter::for('stream', fn (Request $request) => Limit::perMinute((int) config('tradepilot.rate_limits.stream_per_minute', 60))->by('stream:'.($request->user()?->id ?: $request->ip())));
        // MFA settings (signed in) per user; the sign-in code step per PENDING user + IP,
        // so starting a new session does not reset it (AuthController also locks the
        // user's code step after repeated misses, whatever the IP).
        // The mobile app's code step is keyed the same way, by the user its mfa_token belongs to.
        RateLimiter::for('mfa', function (Request $request) {
            $pending = $request->hasSession() ? $request->session()->get('mfa.pending') : null;
            $pending ??= app(MobileMfaChallenges::class)->find($request->input('mfa_token'));

            return Limit::perMinutes(15, 5)->by('mfa:'.($request->user()?->id ?? ($pending['user_id'] ?? 'none').'|'.$request->ip()));
        });
        // STOP TRADING and Close positions: their own generous budget, so heavy
        // dashboard polling (throttle:api) can never block them.
        RateLimiter::for('trading-stop', fn (Request $request) => Limit::perMinute(30)->by('stop:'.($request->user()?->id ?: $request->ip())));

        // Actions that reach a broker or move money.
        RateLimiter::for('trading', fn (Request $request) => Limit::perMinute(30)->by('trade:'.$request->user()?->id));
        RateLimiter::for('broker', fn (Request $request) => Limit::perMinute(12)->by('broker:'.$request->user()?->id));

        // Plain-English strategy drafting calls a paid AI API: a few per hour per user.
        RateLimiter::for('strategy-draft', fn (Request $request) => Limit::perHour((int) config('tradepilot.ai_drafts_per_hour', 10))->by('draft:'.$request->user()?->id));
    }
}
