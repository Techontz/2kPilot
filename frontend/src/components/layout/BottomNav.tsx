"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { isActive, NAVIGATION } from "./nav";

/** Mobile: thumb-friendly bottom tab bar (≥ 56px targets), clears the home indicator. */
export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-line/60 bg-[color-mix(in_oklab,var(--background)_88%,transparent)] backdrop-blur-xl backdrop-saturate-150 lg:hidden">
      <ul className="mx-auto grid max-w-md grid-cols-5">
        {NAVIGATION.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group flex h-16 flex-col items-center justify-center gap-1 text-xs font-semibold transition-colors focus-visible:outline-offset-[-4px]",
                  active ? "text-fg" : "text-fg-muted hover:text-fg",
                )}
              >
                <span className={cn("flex h-7 w-12 items-center justify-center rounded-full transition-colors", active && "bg-[color-mix(in_oklab,var(--primary)_16%,transparent)]")}>
                  <Icon aria-hidden className={cn("size-5 transition-transform group-active:scale-90", active && "text-brand-ink")} strokeWidth={active ? 2.4 : 2} />
                </span>
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
