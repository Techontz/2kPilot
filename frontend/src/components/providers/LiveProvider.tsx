"use client";

import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react";
import { createLiveClient, type LiveClient, type LiveEventName, type LiveHandler, type LiveState } from "@/lib/live";

interface LiveValue {
  client: LiveClient | null;
  state: LiveState;
}

const LiveContext = createContext<LiveValue>({ client: null, state: "idle" });

/** Opens the /api/stream connection for the signed-in session (falls back to polling on its own). */
export function LiveProvider({ children, client: injected }: { children: ReactNode; client?: LiveClient }) {
  const [client] = useState<LiveClient>(() => injected ?? createLiveClient());
  const [state, setState] = useState<LiveState>(client.state);

  useEffect(() => {
    const off = client.onStateChange(setState);
    client.start();
    return () => {
      off();
      client.stop();
    };
  }, [client]);

  return <LiveContext.Provider value={{ client, state }}>{children}</LiveContext.Provider>;
}

/** Current stream state; `open` means events are flowing and polling can slow down. */
export function useLiveState(): LiveState {
  return useContext(LiveContext).state;
}

/** Call `handler(data)` for every `name` event. The latest handler is always used (no resubscribe churn). */
export function useLiveEvent(name: LiveEventName, handler: LiveHandler): void {
  const { client } = useContext(LiveContext);
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  }, [handler]);
  useEffect(() => {
    if (!client) return;
    return client.subscribe(name, (data, event) => ref.current(data, event));
  }, [client, name]);
}

/** Re-run `reload` whenever any of `names` arrives (REST stays the source of truth). */
export function useLiveRefresh(names: readonly LiveEventName[], reload: () => void): void {
  const { client } = useContext(LiveContext);
  const ref = useRef(reload);
  useEffect(() => {
    ref.current = reload;
  }, [reload]);
  const key = names.join(",");
  useEffect(() => {
    if (!client) return;
    const offs = key.split(",").map((name) => client.subscribe(name, () => ref.current()));
    return () => offs.forEach((off) => off());
  }, [client, key]);
}
