"use client";

import { usePathname } from "next/navigation";
import type { CSSProperties, ReactNode } from "react";
import { useAppData } from "../providers/AppDataProvider";
import { BottomNav } from "./BottomNav";
import { EnvironmentStrip } from "./EnvironmentStrip";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/**
 * The faint wash at the top of each page: brand purple on Home/Strategies,
 * neutral elsewhere. A LIVE (real-money) account washes every page in the
 * LIVE red so real money is never mistaken for demo.
 */
function washFor(pathname: string, env: string | undefined): string {
  if (env === "LIVE") return "var(--live)";
  if (pathname === "/" || pathname.startsWith("/strategies")) return "var(--brand-1)";
  return "var(--fg-subtle)";
}

/**
 * Desktop: a dark frame (the "shell") holding two rounded inset panels — the
 * navigation/library panel on the left and the page panel on the right.
 * Mobile: one full-bleed panel with the bottom tab bar.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { account } = useAppData();
  const style = { "--wash": washFor(pathname, account?.environment) } as CSSProperties;
  return (
    <div className="min-h-screen bg-background lg:bg-shell">
      <a href="#main" className="sr-only z-50 rounded-full bg-primary px-4 py-2 font-semibold text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Skip to content
      </a>
      <TopBar />
      <aside className="fixed top-16 bottom-2 left-2 z-20 hidden w-[76px] lg:block xl:w-[264px]">
        <Sidebar />
      </aside>
      <div className="lg:pr-2 lg:pb-2 lg:pl-[92px] xl:pl-[280px]">
        <div style={style} className="relative isolate min-h-[calc(100vh-4rem)] bg-background lg:min-h-[calc(100vh-4.5rem)] lg:overflow-clip lg:rounded-lg">
          <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[360px] bg-[linear-gradient(180deg,color-mix(in_oklab,var(--wash)_10%,transparent)_0%,color-mix(in_oklab,var(--wash)_3%,transparent)_55%,transparent_100%)] transition-[background] duration-700 dark:bg-[linear-gradient(180deg,color-mix(in_oklab,var(--wash)_20%,transparent)_0%,color-mix(in_oklab,var(--wash)_6%,transparent)_55%,transparent_100%)]" />
          <EnvironmentStrip />
          <main id="main" className="mx-auto w-full max-w-[1320px] min-w-0 px-4 pt-6 pb-28 sm:px-6 lg:px-8 lg:pt-8 lg:pb-12">
            {children}
          </main>
        </div>
      </div>
      <BottomNav />
    </div>
  );
}
