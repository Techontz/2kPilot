/**
 * Typed transport to the Laravel API.
 *
 * - Same-origin requests to /api/* (Next.js proxies them to Laravel), so the
 *   session cookie stays first-party and the backend address never reaches
 *   the browser.
 * - CSRF: Laravel sets the XSRF-TOKEN cookie (GET /sanctum/csrf-cookie); it is
 *   echoed in the X-XSRF-TOKEN header on every state-changing request.
 * - Errors are normalised into ApiError {status, code, message, fieldErrors}.
 */

const SAFE_METHODS = new Set(["GET", "HEAD"]);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fieldErrors: Record<string, string[]> = {},
    /** Plain-English problems from the trading engine (e.g. an invalid rule set). */
    readonly problems: string[] = [],
    /** Seconds from the Retry-After header (429 responses), if any. */
    readonly retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** First validation message for a field, if any. */
  field(name: string): string | null {
    return this.fieldErrors[name]?.[0] ?? null;
  }
}

export function readCookie(name: string, cookieString: string = typeof document === "undefined" ? "" : document.cookie): string | null {
  for (const part of cookieString.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

let unauthorizedHandler: (() => void) | null = null;
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

let csrfReady: Promise<void> | null = null;
export function ensureCsrf(force = false): Promise<void> {
  if (force || !readCookie("XSRF-TOKEN")) csrfReady = null;
  csrfReady ??= fetch("/sanctum/csrf-cookie", { credentials: "same-origin", cache: "no-store" }).then(() => undefined);
  return csrfReady;
}

interface Options {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

export function buildUrl(path: string, query?: Options["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `/api${path}${qs ? `?${qs}` : ""}`;
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" };
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method)) {
    await ensureCsrf();
    const token = readCookie("XSRF-TOKEN");
    if (token) headers["X-XSRF-TOKEN"] = token;
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body === undefined ? undefined : isForm ? (options.body as FormData) : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "Cannot reach the 2kPilot server. Check that it is running (make dev).");
  }
  if (response.status === 204) return undefined as T;
  const payload = (await response.json().catch(() => null)) as
    | { message?: string; code?: string; errors?: Record<string, string[]>; problems?: unknown }
    | null;
  if (!response.ok) {
    if (response.status === 419) csrfReady = null; // token expired: refresh next time
    const error = new ApiError(
      response.status,
      payload?.code ?? (response.status === 422 ? "validation_error" : "http_error"),
      payload?.message ?? `Request failed (${response.status})`,
      payload?.errors ?? {},
      Array.isArray(payload?.problems) ? payload.problems.map(String) : [],
      parseRetryAfter(response.headers.get("Retry-After")),
    );
    if (response.status === 401 && !path.startsWith("/auth/")) unauthorizedHandler?.();
    throw error;
  }
  return payload as T;
}

/** Retry-After as seconds (it may also be an HTTP date); null when absent or unreadable. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const at = Date.parse(value);
  return Number.isNaN(at) ? null : Math.max(0, Math.ceil((at - now) / 1000));
}

/** A random key so a confirmed ticket can never be executed twice. */
export function idempotencyKey(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return `t-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}
