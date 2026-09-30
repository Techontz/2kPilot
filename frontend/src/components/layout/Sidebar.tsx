"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { isActive, NAVIGATION } from "@/lib/nav";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-col gap-6 px-3 py-4">
      {NAVIGATION.map((group) => (
        <div key={group.title}>
          <p className="mb-1.5 px-3 text-[11px] font-medium tracking-wider text-fg-subtle uppercase">
            {group.title}
          </p>
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
                      "flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
                      active
                        ? "bg-surface-raised font-medium text-fg"
                        : "text-fg-muted hover:bg-surface-raised/60 hover:text-fg",
                    )}
                  >
                    <Icon aria-hidden className={cn("size-4", active ? "text-accent" : "text-fg-subtle")} />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
