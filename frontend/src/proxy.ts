import { type NextRequest, NextResponse } from "next/server";

export const SESSION_COOKIE = "tradepilot_session";
const PUBLIC_PATHS = new Set(["/login", "/signup"]);

/**
 * Optimistic redirect only: without a session cookie, everything except the
 * public sign-in and sign-up pages goes to /login. Real authentication is
 * enforced by Laravel on every API call — a forged cookie gets nothing but 401s.
 */
export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has(SESSION_COOKIE);
  const isPublic = PUBLIC_PATHS.has(request.nextUrl.pathname);
  if (!hasSession && !isPublic) {
    const url = new URL("/login", request.url);
    // Keep the query so section tabs survive sign-in (e.g. /settings?tab=brokers).
    if (request.nextUrl.pathname !== "/") url.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the API/Sanctum proxy, Next internals and static files.
  matcher: ["/((?!api/|sanctum/|_next/|favicon.ico|.*\\.[a-zA-Z0-9]+$).*)"],
};
