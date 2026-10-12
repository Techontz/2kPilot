<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Laravel\Sanctum\PersonalAccessToken;
use Symfony\Component\HttpFoundation\Response;

/**
 * "web.only": actions the mobile app may not perform. A request signed in
 * with a mobile bearer token (not the dashboard's cookie session) gets
 * 403 `web_only`: changing the password, setting up or turning off two-factor
 * authentication, and platform operations. Entering LIVE (real-money) mode is
 * refused in TradingController with `live_requires_web`.
 */
class EnsureWebSession
{
    public function handle(Request $request, Closure $next): Response
    {
        if (self::viaToken($request)) {
            return response()->json([
                'message' => 'This action is only available on the 2kPilot website.',
                'code' => 'web_only',
            ], 403);
        }

        return $next($request);
    }

    /** True when the request is authenticated with a Sanctum bearer token (the mobile app). */
    public static function viaToken(Request $request): bool
    {
        return $request->user()?->currentAccessToken() instanceof PersonalAccessToken;
    }
}
