import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backoffDelay, createLiveClient, type EventSourceLike, isLive, type LiveState } from "./live";

/** Minimal controllable EventSource. */
class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];
  readyState = 0;
  onopen: EventSourceLike["onopen"] = null;
  onerror: EventSourceLike["onerror"] = null;
  closed = false;
  listeners = new Map<string, ((e: MessageEvent) => void)[]>();
  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, listener: (e: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  open() {
    this.readyState = 1;
    this.onopen?.call(this, new Event("open"));
  }
  /** What a 404 / refused connection looks like to EventSource: an error, then CLOSED. */
  fail() {
    this.readyState = 2;
    this.onerror?.call(this, new Event("error"));
  }
  emit(type: string, data: string) {
    for (const l of this.listeners.get(type) ?? []) l(new MessageEvent(type, { data }));
  }
}

const latest = () => FakeEventSource.instances[FakeEventSource.instances.length - 1]!;

function makeClient() {
  const states: LiveState[] = [];
  const client = createLiveClient({
    createEventSource: (url) => new FakeEventSource(url),
    baseDelayMs: 1000,
    maxDelayMs: 8000,
    maxFailures: 3,
    fallbackRetryMs: 60_000,
    jitter: 0,
  });
  client.onStateChange((s) => states.push(s));
  return { client, states };
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.instances = [];
});
afterEach(() => {
  vi.useRealTimers();
});

describe("backoffDelay", () => {
  it("doubles from the base and caps at the max", () => {
    expect([1, 2, 3, 4, 5].map((n) => backoffDelay(n, 1000, 8000))).toEqual([1000, 2000, 4000, 8000, 8000]);
  });
  it("adds bounded jitter", () => {
    expect(backoffDelay(1, 1000, 8000, 0.5, () => 1)).toBe(1500);
  });
});

describe("live client", () => {
  it("connects to /api/stream and dispatches parsed named events", () => {
    const { client, states } = makeClient();
    const onStatus = vi.fn();
    client.subscribe("trading.status", onStatus);
    client.start();
    expect(latest().url).toBe("/api/stream");
    latest().open();
    expect(isLive(client.state)).toBe(true);
    latest().emit("trading.status", '{"kill_switch_engaged":true}');
    latest().emit("trade.closed", "{}"); // nobody subscribed: ignored
    expect(onStatus).toHaveBeenCalledWith({ kill_switch_engaged: true }, expect.any(MessageEvent));
    expect(states).toEqual(["connecting", "open"]);
  });

  it("falls back to polling after repeated failures (e.g. 404) and retries later", () => {
    const { client, states } = makeClient();
    client.start();
    latest().fail(); // attempt 1 fails → retry in 1s
    expect(client.state).toBe("connecting");
    vi.advanceTimersByTime(1000);
    expect(FakeEventSource.instances).toHaveLength(2);
    latest().fail(); // attempt 2 → retry in 2s
    vi.advanceTimersByTime(2000);
    latest().fail(); // attempt 3 → give up for now
    expect(client.state).toBe("fallback");
    expect(isLive(client.state)).toBe(false);
    expect(FakeEventSource.instances.every((s) => s.closed)).toBe(true);

    vi.advanceTimersByTime(59_999);
    expect(FakeEventSource.instances).toHaveLength(3); // no hammering while polling
    vi.advanceTimersByTime(1);
    expect(FakeEventSource.instances).toHaveLength(4); // periodic retry
    latest().open();
    expect(client.state).toBe("open");
    expect(states).toEqual(["connecting", "fallback", "open"]);
  });

  it("reconnects quickly after an established stream drops", () => {
    const { client } = makeClient();
    client.start();
    latest().open();
    latest().fail();
    expect(client.state).toBe("connecting");
    vi.advanceTimersByTime(1000);
    latest().open();
    expect(client.state).toBe("open");
  });

  it("uses polling only when EventSource does not exist", () => {
    const client = createLiveClient({ createEventSource: null });
    client.start();
    expect(client.state).toBe("fallback");
  });

  it("stops cleanly: closes the source and cancels pending retries", () => {
    const { client } = makeClient();
    client.start();
    latest().fail();
    client.stop();
    vi.advanceTimersByTime(10_000);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(client.state).toBe("closed");
  });

  it("isolates a throwing handler", () => {
    const { client } = makeClient();
    const ok = vi.fn();
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    client.subscribe("notification", () => {
      throw new Error("boom");
    });
    client.subscribe("notification", ok);
    client.start();
    latest().open();
    latest().emit("notification", "plain text");
    expect(ok).toHaveBeenCalledWith("plain text", expect.any(MessageEvent));
    spy.mockRestore();
  });
});
