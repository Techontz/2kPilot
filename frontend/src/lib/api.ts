/**
 * Minimal typed client for the 2kFX API.
 *
 * - Same-origin requests to /api/v1 (proxied by Next.js), cookies included.
 * - Echoes the CSRF cookie in X-CSRF-Token on state-changing requests.
 * - Normalises the backend error envelope into ApiError.
 * No business logic lives here — only transport.
 */

export const API_BASE = "/api/v1";
const CSRF_COOKIE = "fx_csrf";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly correlationId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function readCookie(name: string, cookieString: string = document.cookie): string | null {
  for (const part of cookieString.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

/** Called when an authenticated request gets 401 (session expired/revoked). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "network_error", "Cannot reach the 2kFX server. Check that it is running.");
  }

  if (response.status === 204) return undefined as T;

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const envelope = (payload as { error?: { code?: string; message?: string; correlation_id?: string } } | null)
      ?.error;
    const error = new ApiError(
      response.status,
      envelope?.code ?? "http_error",
      envelope?.message ?? `Request failed (${response.status})`,
      envelope?.correlation_id ?? null,
    );
    if (response.status === 401 && path !== "/auth/login") onUnauthorized?.();
    throw error;
  }
  return payload as T;
}
