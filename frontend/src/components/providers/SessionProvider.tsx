"use client";

import { useRouter } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect } from "react";
import { apiRequest, setUnauthorizedHandler } from "@/lib/api";
import type { SessionInfo, User } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

interface SessionContextValue {
  user: User;
  isOwner: boolean;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const session = useApiResource<SessionInfo>("/auth/me");

  useEffect(() => {
    setUnauthorizedHandler(() => router.replace("/login?expired=1"));
    return () => setUnauthorizedHandler(null);
  }, [router]);

  if (session.error?.status === 401) return null; // redirect in progress
  if (!session.data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-fg-muted">
        {session.error ? session.error.message : "Loading 2kFX…"}
      </div>
    );
  }

  const logout = async () => {
    await apiRequest("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  };

  const user = session.data.user;
  return (
    <SessionContext.Provider value={{ user, isOwner: user.role === "owner", logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside SessionProvider");
  return ctx;
}
