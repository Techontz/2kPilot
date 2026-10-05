"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, onUnauthorized } from "@/lib/api";
import type { User } from "@/lib/types";

interface SessionValue {
  user: User;
  isOwner: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

/** Loads the signed-in user; any 401 sends the browser to /login. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);

  const toLogin = useCallback(() => {
    const next = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
    router.replace(`/login${next}`);
  }, [pathname, router]);

  const refresh = useCallback(
    () => api<{ user: User }>("/auth/me").then((body) => setUser(body.user), toLogin),
    [toLogin],
  );

  useEffect(() => {
    onUnauthorized(toLogin);
    api<{ user: User }>("/auth/me").then((body) => setUser(body.user), toLogin);
    return () => onUnauthorized(null);
  }, [toLogin]);

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }, [router]);

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status">
        <span className="size-5 animate-spin rounded-full border-2 border-line-strong border-t-accent" aria-hidden />
        <span className="sr-only">Loading</span>
      </div>
    );
  }
  return (
    <SessionContext.Provider value={{ user, isOwner: user.role === "owner", refresh, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
