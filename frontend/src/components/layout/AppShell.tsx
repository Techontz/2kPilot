"use client";

import { X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { LiveBanner } from "./LiveBanner";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

function Brand() {
  return (
    <div className="flex h-14 items-center gap-2 border-b border-line px-5">
      <span className="flex size-7 items-center justify-center rounded-md bg-accent text-xs font-bold text-canvas">
        2k
      </span>
      <span className="text-sm font-semibold tracking-tight">
        2kFX <span className="text-fg-muted">ROBOT</span>
      </span>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { status } = useSystemStatus();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen">
      {status && <LiveBanner mode={status.trading.trading_mode} />}
      <div className="flex">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 overflow-y-auto border-r border-line bg-surface/40 lg:block">
          <Brand />
          <Sidebar />
        </aside>

        {menuOpen && (
          <div className="fixed inset-0 z-50 lg:hidden">
            <button
              type="button"
              aria-label="Close navigation"
              className="absolute inset-0 bg-black/60"
              onClick={() => setMenuOpen(false)}
            />
            <aside className="relative h-full w-64 overflow-y-auto border-r border-line bg-surface">
              <button
                type="button"
                onClick={() => setMenuOpen(false)}
                className="absolute top-4 right-3 rounded-md p-1 text-fg-muted hover:bg-surface-raised"
                aria-label="Close navigation"
              >
                <X className="size-4" />
              </button>
              <Brand />
              <Sidebar onNavigate={() => setMenuOpen(false)} />
            </aside>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar onOpenMenu={() => setMenuOpen(true)} />
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 lg:px-8 lg:py-8">{children}</main>
        </div>
      </div>
    </div>
  );
}
