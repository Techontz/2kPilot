/**
 * Live updates (Server-Sent Events) from Laravel's GET /api/stream.
 *
 * The generic /api/* rewrite in next.config.ts buffers responses, which would
 * hold every event back until the stream ends. This Route Handler (checked
 * before rewrites) pipes the upstream body through untouched instead, so each
 * event reaches the browser immediately. The browser's session cookie and
 * Origin/Referer are forwarded so Sanctum authenticates it like any other
 * dashboard request; closing the tab aborts the upstream request too.
 *
 * X-Forwarded-For is NOT passed on: a client could put any address in it,
 * and Laravel trusts that header from this server (TRUSTED_PROXIES). The
 * stream's rate limit is per user, so the client IP is not needed here.
 */
export const dynamic = "force-dynamic";

const FORWARDED = ["cookie", "origin", "referer", "user-agent", "accept-language"];

export async function GET(request: Request): Promise<Response> {
  const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8421";
  const headers = new Headers({ Accept: "text/event-stream", "X-Requested-With": "XMLHttpRequest" });
  for (const name of FORWARDED) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${backend}/api/stream`, { headers, cache: "no-store", signal: request.signal, redirect: "manual" });
  } catch {
    return Response.json({ message: "Live updates are unavailable.", code: "stream_unavailable" }, { status: 503 });
  }
  const out = new Headers({
    "Content-Type": upstream.headers.get("content-type") ?? "text/event-stream",
    "Cache-Control": "no-cache, no-store, no-transform, private",
    "X-Accel-Buffering": "no",
    Connection: "keep-alive",
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}
