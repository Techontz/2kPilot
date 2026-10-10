"use client";

import { useRouter } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, onUnauthorized } from "@/lib/api";
import type { User } from "@/lib/types";

interface SessionValue {
  user: User;
  isAdmin: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

/** Where to come back to after signing in: the current path WITH its query (e.g. /settings?tab=brokers). */
export function loginUrl(location: { pathname: string; search: string }): string {
  const here = `${location.pathname}${location.search}`;
  return location.pathname && here !== "/" ? `/login?next=${encodeURIComponent(here)}` : "/login";
}

/**
 * Loads the signed-in user once per page load; a 401 (here or from any API
 * call) sends the browser to /login. A busy or unreachable server is retried
 * — it never signs the user out.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  // Reads the location when called, so it does not change (and reload the user) on navigation.
  const toLogin = useCallback(() => {
    router.replace(loginUrl(window.location));
  }, [router]);

  const load = useCallback(async (): Promise<void> => {
    for (let attempt = 0; ; attempt++) {
      try {
        const body = await api<{ user: User }>("/auth/me");
        setUnreachable(false);
        setUser(body.user);
        return;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          toLogin();
          return;
        }
        if (attempt >= 2) setUnreachable(true);
        await new Promise((resolve) => setTimeout(resolve, Math.min(10_000, 1000 * (attempt + 1))));
      }
    }
  }, [toLogin]);

  const refresh = load;

  useEffect(() => {
    onUnauthorized(toLogin);
    const first = window.setTimeout(() => void load(), 0); // state is set after the request, not in the effect
    return () => {
      window.clearTimeout(first);
      onUnauthorized(null);
    };
  }, [toLogin, load]);

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }, [router]);

  if (!user) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3" role="status">
        <span className="size-5 animate-spin rounded-full border-2 border-line-strong border-t-primary" aria-hidden />
        {unreachable ? <p className="text-sm text-fg-muted">Can&apos;t reach the 2kPilot server. Retrying…</p> : <span className="sr-only">Loading</span>}
      </div>
    );
  }
  return (
    <SessionContext.Provider value={{ user, isAdmin: user.role === "admin", refresh, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
