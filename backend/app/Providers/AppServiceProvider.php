<?php

namespace App\Providers;

use App\Models\User;
use App\Services\Engine\EngineClient;
use App\Services\Security\BrokerVault;
use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Gate;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->singleton(EngineClient::class, fn () => new EngineClient(
            config('fx.engine.url'),
            config('fx.engine.secret'),
            (int) config('fx.engine.timeout'),
        ));
        $this->app->singleton(BrokerVault::class, fn () => new BrokerVault(config('fx.broker_credentials_key')));
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

        // Global trading controls (stop/resume, mode, close positions): owners only.
        Gate::define('operate-trading', fn (User $user) => $user->is_active && $user->isOwner());
        Gate::define('view-audit', fn (User $user) => $user->is_active && $user->isOwner());

        $this->configureRateLimits();
    }

    private function configureRateLimits(): void
    {
        RateLimiter::for('api', fn (Request $request) => Limit::perMinute(300)->by($request->user()?->id ?: $request->ip()));

        // Login and MFA: per account and per IP, so neither can be brute-forced.
        RateLimiter::for('login', fn (Request $request) => [
            Limit::perMinutes(15, (int) config('fx.login_attempts', 5))->by('login:'.strtolower((string) $request->input('email')).'|'.$request->ip()),
            Limit::perMinutes(15, 4 * (int) config('fx.login_attempts', 5))->by('login-ip:'.$request->ip()),
        ]);
        RateLimiter::for('mfa', fn (Request $request) => Limit::perMinutes(15, 5)->by('mfa:'.($request->user()?->id ?? $request->session()->getId())));

        // Actions that reach a broker or move money.
        RateLimiter::for('trading', fn (Request $request) => Limit::perMinute(30)->by('trade:'.$request->user()?->id));
        RateLimiter::for('broker', fn (Request $request) => Limit::perMinute(12)->by('broker:'.$request->user()?->id));
    }
}
