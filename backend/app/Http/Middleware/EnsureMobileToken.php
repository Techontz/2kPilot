<?php

namespace App\Http\Middleware;

use App\Services\Mobile\MobileTokens;
use Closure;
use Illuminate\Http\Request;
use Laravel\Sanctum\PersonalAccessToken;
use Symfony\Component\HttpFoundation\Response;

/** "mobile.token": the mobile app's own endpoints need its bearer token (ability "mobile"). */
class EnsureMobileToken
{
    public function handle(Request $request, Closure $next): Response
    {
        $token = $request->user()?->currentAccessToken();
        if (! $token instanceof PersonalAccessToken || ! $token->can(MobileTokens::ABILITY)) {
            return response()->json([
                'message' => 'Sign in from the 2kPilot mobile app.',
                'code' => 'mobile_token_required',
            ], 403);
        }

        return $next($request);
    }
}
