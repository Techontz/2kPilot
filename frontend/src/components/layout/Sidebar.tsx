"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useAppData } from "../providers/AppDataProvider";
import { isActive, NAVIGATION } from "./nav";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { unread } = useAppData();
  return (
    <nav aria-label="Main" className="flex h-full flex-col">
      <Link href="/" onClick={onNavigate} className="flex h-14 shrink-0 items-center gap-2.5 px-5">
        <span className="flex size-7 items-center justify-center rounded-md bg-accent text-[11px] font-bold tracking-tight text-canvas">2k</span>
        <span className="text-sm font-semibold tracking-tight text-fg">2kFX ROBOT</span>
      </Link>
      <div className="flex-1 space-y-5 overflow-y-auto px-3 py-3">
        {NAVIGATION.map((group) => (
          <div key={group.title}>
            <p className="px-2 pb-1.5 text-[11px] font-medium tracking-wide text-fg-subtle uppercase">{group.title}</p>
            <ul className="space-y-0.5">
              {group.items.map(({ href, label, icon: Icon }) => {
                const active = isActive(pathname, href);
                return (
                  <li key={href}>
                    <Link
                      href={href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex h-8 items-center gap-2.5 rounded-md px-2 text-sm transition-colors",
                        active ? "bg-surface-raised font-medium text-fg" : "text-fg-muted hover:bg-surface-raised/60 hover:text-fg",
                      )}
                    >
                      <Icon aria-hidden className={cn("size-4 shrink-0", active ? "text-accent" : "text-fg-subtle")} />
                      <span className="flex-1">{label}</span>
                      {href === "/notifications" && unread > 0 && (
                        <span className="num rounded-full bg-accent/15 px-1.5 text-[11px] font-medium text-accent">{unread > 99 ? "99+" : unread}</span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}
