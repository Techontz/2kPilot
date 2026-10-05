import { type NextRequest, NextResponse } from "next/server";

export const SESSION_COOKIE = "twokfx_session";

/**
 * Optimistic redirect only: without a session cookie, go to /login. Real
 * authentication is enforced by Laravel on every API call — a forged cookie
 * gets nothing but 401s.
 */
export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has(SESSION_COOKIE);
  const isLogin = request.nextUrl.pathname === "/login";
  if (!hasSession && !isLogin) {
    const url = new URL("/login", request.url);
    if (request.nextUrl.pathname !== "/") url.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the API/Sanctum proxy, Next internals and static files.
  matcher: ["/((?!api/|sanctum/|_next/|favicon.ico|.*\\.[a-zA-Z0-9]+$).*)"],
};
