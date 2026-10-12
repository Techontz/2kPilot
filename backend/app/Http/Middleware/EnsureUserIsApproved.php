<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * A new sign-up sees nothing until an admin approves the account. Only
 * GET /api/auth/me answers (so the dashboard can show the waiting page);
 * signing out never passes through here.
 */
class EnsureUserIsApproved
{
    public function handle(Request $request, Closure $next): Response
    {
        $user = $request->user();
        if ($user !== null && ! $user->isApproved() && ! $request->is('api/auth/me')) {
            return response()->json([
                'message' => 'Your account is waiting for an administrator to approve it.',
                'code' => 'approval_pending',
            ], 403);
        }

        return $next($request);
    }
}
