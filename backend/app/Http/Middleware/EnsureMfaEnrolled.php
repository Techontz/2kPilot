<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/** With TP_REQUIRE_MFA=true, users must set up two-factor authentication first. */
class EnsureMfaEnrolled
{
    public function handle(Request $request, Closure $next): Response
    {
        $user = $request->user();
        if ($user !== null && config('tradepilot.mfa.required') && ! $user->hasMfa()) {
            return response()->json([
                'message' => 'Set up two-factor authentication to continue (Settings → Security).',
                'code' => 'mfa_enrollment_required',
            ], 403);
        }

        return $next($request);
    }
}
