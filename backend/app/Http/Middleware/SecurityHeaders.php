<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/** Conservative security headers on every API response. */
class SecurityHeaders
{
    public function handle(Request $request, Closure $next): Response
    {
        $response = $next($request);
        $response->headers->set('X-Content-Type-Options', 'nosniff');
        $response->headers->set('X-Frame-Options', 'DENY');
        $response->headers->set('Referrer-Policy', 'same-origin');
        // Live updates (SSE) must also never be transformed (compressed/buffered) by a proxy.
        $stream = str_starts_with((string) $response->headers->get('Content-Type'), 'text/event-stream');
        $response->headers->set('Cache-Control', $stream ? 'no-cache, no-store, no-transform, private' : 'no-store, private');
        if ($request->isSecure()) {
            $response->headers->set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
        }

        return $response;
    }
}
