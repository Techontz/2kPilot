<?php

use App\Exceptions\DomainException;
use App\Http\Middleware\EnsureMfaEnrolled;
use App\Http\Middleware\EnsureMobileToken;
use App\Http\Middleware\EnsureUserIsActive;
use App\Http\Middleware\EnsureUserIsApproved;
use App\Http\Middleware\EnsureWebSession;
use App\Http\Middleware\SecurityHeaders;
use App\Services\Engine\EngineException;
use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\Exceptions;
use Illuminate\Foundation\Configuration\Middleware;
use Illuminate\Http\Request;

return Application::configure(basePath: dirname(__DIR__))
    ->withRouting(
        web: __DIR__.'/../routes/web.php',
        api: __DIR__.'/../routes/api.php',
        commands: __DIR__.'/../routes/console.php',
        health: '/up',
    )
    ->withMiddleware(function (Middleware $middleware): void {
        // Cookie sessions + CSRF for the Next.js dashboard (Sanctum SPA auth).
        // The mobile app sends no Origin/Referer: Sanctum treats its requests as
        // stateless and authenticates the bearer token (no session, no CSRF).
        $middleware->statefulApi();
        // Proxies trusted for X-Forwarded-For (the client IP behind rate limits and
        // audit logs) come from config/trustedproxy.php (TRUSTED_PROXIES).
        $middleware->append(SecurityHeaders::class);
        // An API with no login page: guests get 401 JSON, never a redirect
        // (also for EventSource, which asks for text/event-stream).
        $middleware->redirectGuestsTo(fn () => null);
        $middleware->alias([
            'active' => EnsureUserIsActive::class,
            'approved' => EnsureUserIsApproved::class,  // new sign-ups wait for an admin
            'mfa.enrolled' => EnsureMfaEnrolled::class,
            'web.only' => EnsureWebSession::class,       // refused with a mobile token
            'mobile.token' => EnsureMobileToken::class,  // needs a mobile token
        ]);
    })
    ->withExceptions(function (Exceptions $exceptions): void {
        $exceptions->shouldRenderJsonWhen(
            fn (Request $request) => $request->is('api/*') || $request->expectsJson(),
        );
        // Business-rule refusals and engine errors: {message, code} with a clear status.
        $exceptions->render(fn (DomainException $e) => response()->json(
            ['message' => $e->getMessage(), 'code' => $e->errorCode], $e->status));
        $exceptions->render(fn (EngineException $e) => response()->json(
            ['message' => $e->getMessage(), 'code' => $e->errorCode] + ($e->problems() ? ['problems' => $e->problems()] : []), $e->httpStatus()));
        // Never log secrets that might sit in request input.
        $exceptions->dontFlash(['password', 'password_confirmation', 'current_password', 'token', 'code', 'mfa_code', 'mfa_token', 'fcm_token']);
    })->create();
