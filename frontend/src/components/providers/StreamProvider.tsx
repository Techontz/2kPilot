"use client";

import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

export type StreamTopic =
  | "status"
  | "notification"
  | "notification_read"
  | "journal"
  | "broker"
  | "account"
  | "evaluation";

type Listener = (topic: StreamTopic, data: Record<string, unknown>) => void;

interface StreamValue {
  connected: boolean;
  subscribe: (listener: Listener) => () => void;
}

const StreamContext = createContext<StreamValue | null>(null);
const TOPICS: StreamTopic[] = ["status", "notification", "notification_read", "journal", "broker", "account", "evaluation"];

/**
 * One server-sent-events connection for the whole dashboard. The browser's
 * EventSource reconnects automatically; `connected` drives the live indicator.
 */
export function StreamProvider({ children }: { children: ReactNode }) {
  const listeners = useRef(new Set<Listener>());
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE}/stream`, { withCredentials: true });
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    const handlers = TOPICS.map((topic) => {
      const handler = (event: MessageEvent<string>) => {
        try {
          const payload = JSON.parse(event.data) as { data: Record<string, unknown> };
          listeners.current.forEach((listener) => listener(topic, payload.data));
        } catch {
          /* ignore malformed events */
        }
      };
      source.addEventListener(topic, handler);
      return [topic, handler] as const;
    });
    return () => {
      handlers.forEach(([topic, handler]) => source.removeEventListener(topic, handler));
      source.close();
    };
  }, []);

  const value: StreamValue = {
    connected,
    subscribe: (listener) => {
      listeners.current.add(listener);
      return () => listeners.current.delete(listener);
    },
  };
  return <StreamContext.Provider value={value}>{children}</StreamContext.Provider>;
}

export function useStream(): StreamValue {
  const ctx = useContext(StreamContext);
  return ctx ?? { connected: false, subscribe: () => () => undefined };
}

/** Call `onEvent` (debounced) whenever one of `topics` arrives. */
export function useLiveRefresh(topics: StreamTopic[], onEvent: () => void, delayMs = 600): void {
  const { subscribe } = useStream();
  const callback = useRef(onEvent);
  useEffect(() => {
    callback.current = onEvent;
  }, [onEvent]);
  const key = topics.join(",");
  useEffect(() => {
    const wanted = new Set(key.split(","));
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = subscribe((topic) => {
      if (!wanted.has(topic)) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => callback.current(), delayMs);
    });
    return () => {
      unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, [key, subscribe, delayMs]);
}
