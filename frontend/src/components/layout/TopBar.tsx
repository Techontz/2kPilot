"use client";

import { Bell, LogOut, Menu, Settings } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAppData } from "../providers/AppDataProvider";
import { useSession } from "../providers/SessionProvider";
import { AccountSwitcher } from "./AccountSwitcher";
import { RobotStatusPill, StopTradingButton } from "./TradingControls";

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const { unread } = useAppData();
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-line bg-canvas/95 px-4 backdrop-blur sm:px-6">
      <button type="button" onClick={onMenu} className="rounded-md p-2 text-fg-muted hover:bg-surface-raised lg:hidden" aria-label="Open menu">
        <Menu className="size-5" />
      </button>
      <div className="min-w-0 flex-1 sm:flex-none">
        <AccountSwitcher />
      </div>
      <div className="hidden flex-1 sm:block" />
      <RobotStatusPill />
      <StopTradingButton />
      <Link href="/notifications" className="relative hidden rounded-md p-2 text-fg-muted hover:bg-surface-raised hover:text-fg sm:block" aria-label={`Notifications (${unread} unread)`}>
        <Bell className="size-5" />
        {unread > 0 && <span className="absolute top-1.5 right-1.5 size-2 rounded-full bg-accent" aria-hidden />}
      </Link>
      <UserMenu />
    </header>
  );
}

function UserMenu() {
  const { user, logout } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const initials = user.name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div ref={ref} className="relative hidden sm:block">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-label="Account menu" aria-expanded={open}
        className="flex size-9 items-center justify-center rounded-full border border-line bg-surface-raised text-xs font-semibold text-fg hover:border-line-strong">
        {initials}
      </button>
      {open && (
        <div className="absolute top-full right-0 z-40 mt-2 w-60 rounded-xl border border-line-strong bg-surface-raised p-1.5 shadow-2xl shadow-black/50">
          <div className="px-2.5 py-2">
            <p className="truncate text-sm font-medium text-fg">{user.name}</p>
            <p className="truncate text-xs text-fg-subtle">{user.email} · {user.role}</p>
          </div>
          <Link href="/settings" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-fg-muted hover:bg-surface-hover hover:text-fg">
            <Settings className="size-4" aria-hidden /> Settings & security
          </Link>
          <button type="button" onClick={() => void logout()} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-fg-muted hover:bg-surface-hover hover:text-fg">
            <LogOut className="size-4" aria-hidden /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
