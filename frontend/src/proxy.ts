import { type NextRequest, NextResponse } from "next/server";

/**
 * Optimistic auth redirect only: if there is no session cookie, send the
 * user to /login. Real authentication is enforced by the backend on every
 * API call — a forged cookie gets nothing but 401s.
 */
export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has("fx_session");
  const isLogin = request.nextUrl.pathname === "/login";
  if (!hasSession && !isLogin) {
    const url = new URL("/login", request.url);
    if (request.nextUrl.pathname !== "/") url.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the API proxy, Next internals and static files.
  matcher: ["/((?!api/|_next/|favicon.ico|.*\\.[a-zA-Z0-9]+$).*)"],
};
