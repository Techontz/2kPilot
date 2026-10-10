/**
 * Live updates over Server-Sent Events: GET /api/stream (same origin, so the
 * Sanctum session cookie authenticates it, and Next.js proxies it to Laravel).
 *
 * The stream is an *accelerator*, never a dependency. Consumers keep polling
 * whenever the client is not `open` (see `isLive`), so the dashboard works the
 * same — only slower — while the endpoint is missing (404), the server is down,
 * or a proxy buffers the response.
 *
 * Reconnect policy:
 *   - Any error closes the EventSource (we do our own backoff instead of the
 *     browser's fixed ~3 s retry) and schedules a reconnect with exponential
 *     backoff + jitter: base, 2×base, 4×base … capped at maxDelayMs.
 *   - A connection that never opened counts as a failure. After
 *     `maxFailures` consecutive failures the client enters `fallback`: polling
 *     carries the app and the stream is re-tried only every `fallbackRetryMs`.
 *   - A connection that opened and later dropped resets the failure count.
 */

export const LIVE_EVENTS = ["trading.status", "account.balance", "trade.opened", "trade.closed", "notification"] as const;
export type LiveEventName = (typeof LIVE_EVENTS)[number];

/** idle: not started · connecting: trying · open: events flowing · fallback: polling only · closed: stopped. */
export type LiveState = "idle" | "connecting" | "open" | "fallback" | "closed";

export type LiveHandler = (data: unknown, event: MessageEvent) => void;

/** The subset of EventSource we use (lets tests inject a fake). */
export interface EventSourceLike {
  readonly readyState: number;
  onopen: ((this: EventSourceLike, ev: Event) => unknown) | null;
  onerror: ((this: EventSourceLike, ev: Event) => unknown) | null;
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}

export interface LiveClientOptions {
  url?: string;
  events?: readonly string[];
  /** Defaults to `new EventSource(url, { withCredentials: true })`; null when EventSource is unavailable. */
  createEventSource?: ((url: string) => EventSourceLike) | null;
  baseDelayMs?: number;
  maxDelayMs?: number;
  maxFailures?: number;
  fallbackRetryMs?: number;
  /** 0..1 — random share added to each delay so many tabs do not reconnect in lockstep. */
  jitter?: number;
  random?: () => number;
}

export interface LiveClient {
  readonly state: LiveState;
  start(): void;
  stop(): void;
  subscribe(name: string, handler: LiveHandler): () => void;
  onStateChange(listener: (state: LiveState) => void): () => void;
}

export function isLive(state: LiveState): boolean {
  return state === "open";
}

/** Delay before reconnect attempt `attempt` (1-based). Exported for tests. */
export function backoffDelay(attempt: number, base: number, max: number, jitter = 0, random: () => number = Math.random): number {
  const exp = Math.min(max, base * 2 ** Math.max(0, attempt - 1));
  return Math.round(exp + exp * jitter * random());
}

function defaultFactory(): ((url: string) => EventSourceLike) | null {
  if (typeof window === "undefined" || typeof window.EventSource === "undefined") return null;
  return (url) => new window.EventSource(url, { withCredentials: true }) as unknown as EventSourceLike;
}

function parse(data: unknown): unknown {
  if (typeof data !== "string") return data;
  try {
    return JSON.parse(data);
  } catch {
    return data;
  }
}

export function createLiveClient(options: LiveClientOptions = {}): LiveClient {
  const url = options.url ?? "/api/stream";
  const events = options.events ?? LIVE_EVENTS;
  const factory = options.createEventSource === undefined ? defaultFactory() : options.createEventSource;
  const base = options.baseDelayMs ?? 1000;
  const maxDelay = options.maxDelayMs ?? 30_000;
  const maxFailures = options.maxFailures ?? 3;
  const fallbackRetry = options.fallbackRetryMs ?? 120_000;
  const jitter = options.jitter ?? 0.2;
  const random = options.random ?? Math.random;

  const handlers = new Map<string, Set<LiveHandler>>();
  const stateListeners = new Set<(state: LiveState) => void>();
  let state: LiveState = "idle";
  let source: EventSourceLike | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let failures = 0;
  let running = false;

  const setState = (next: LiveState) => {
    if (next === state) return;
    state = next;
    for (const listener of stateListeners) listener(next);
  };

  const dispatch = (name: string, event: MessageEvent) => {
    const set = handlers.get(name);
    if (!set?.size) return;
    const data = parse(event.data);
    for (const handler of set) {
      try {
        handler(data, event);
      } catch (error) {
        console.error(`live: handler for "${name}" failed`, error);
      }
    }
  };

  const clearTimer = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };

  const closeSource = () => {
    if (!source) return;
    source.onopen = null;
    source.onerror = null;
    source.close();
    source = null;
  };

  const schedule = (delay: number) => {
    clearTimer();
    timer = setTimeout(() => {
      timer = null;
      connect();
    }, delay);
  };

  const connect = () => {
    if (!running) return;
    if (!factory) {
      setState("fallback"); // no EventSource in this environment: polling only, forever
      return;
    }
    closeSource();
    if (state !== "fallback") setState("connecting");
    let opened = false;
    let es: EventSourceLike;
    try {
      es = factory(url);
    } catch {
      failures += 1;
      afterFailure();
      return;
    }
    source = es;
    es.onopen = () => {
      opened = true;
      failures = 0;
      setState("open");
    };
    es.onerror = () => {
      if (source !== es) return;
      closeSource();
      if (opened) failures = 0;
      failures += 1;
      afterFailure();
    };
    for (const name of events) es.addEventListener(name, (event) => dispatch(name, event));
  };

  const afterFailure = () => {
    if (!running) return;
    if (failures >= maxFailures) {
      setState("fallback");
      schedule(fallbackRetry);
    } else {
      if (state === "open") setState("connecting");
      schedule(backoffDelay(failures, base, maxDelay, jitter, random));
    }
  };

  return {
    get state() {
      return state;
    },
    start() {
      if (running) return;
      running = true;
      failures = 0;
      connect();
    },
    stop() {
      running = false;
      clearTimer();
      closeSource();
      setState("closed");
    },
    subscribe(name, handler) {
      let set = handlers.get(name);
      if (!set) handlers.set(name, (set = new Set()));
      set.add(handler);
      return () => {
        set.delete(handler);
      };
    },
    onStateChange(listener) {
      stateListeners.add(listener);
      return () => {
        stateListeners.delete(listener);
      };
    },
  };
}
