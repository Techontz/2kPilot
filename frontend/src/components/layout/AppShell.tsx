"use client";

import { X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { EnvironmentStrip } from "./EnvironmentStrip";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 border-r border-line bg-surface lg:block">
        <Sidebar />
      </aside>
      {menuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button type="button" className="absolute inset-0 bg-black/60" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-72 max-w-[85vw] border-r border-line bg-surface">
            <button type="button" onClick={() => setMenuOpen(false)} className="absolute top-3.5 right-3 rounded-md p-1.5 text-fg-muted hover:bg-surface-raised" aria-label="Close menu">
              <X className="size-5" />
            </button>
            <Sidebar onNavigate={() => setMenuOpen(false)} />
          </aside>
        </div>
      )}
      <TopBar onMenu={() => setMenuOpen(true)} />
      <EnvironmentStrip />
      <main className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:py-8">{children}</main>
    </div>
  );
}
