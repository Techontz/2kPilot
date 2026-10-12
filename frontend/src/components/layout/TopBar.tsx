"use client";

import { Bell, LogOut, Monitor, Moon, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { useTheme } from "@/components/providers/ThemeProvider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { isThemePreference } from "@/lib/theme";
import { useAppData } from "../providers/AppDataProvider";
import { useSession } from "../providers/SessionProvider";
import { AccountSwitcher } from "./AccountSwitcher";
import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";
import { ModePill } from "./ModePill";
import { BotStatus, TradingToggle } from "./TradingControls";

export function TopBar() {
  const { unread } = useAppData();
  return (
    <header className="sticky top-0 z-30 border-b border-line/60 bg-[color-mix(in_oklab,var(--background)_85%,transparent)] pt-[env(safe-area-inset-top)] backdrop-blur-xl backdrop-saturate-150 lg:border-b-0 lg:bg-shell lg:pt-0 lg:backdrop-blur-none">
      <div className="flex h-16 items-center gap-2 px-[max(1rem,env(safe-area-inset-left))] sm:gap-3 sm:px-5 lg:px-2 lg:pr-4">
        <Link href="/" aria-label="2kPilot home" className="hidden shrink-0 rounded-lg min-[420px]:block lg:flex lg:w-[76px] lg:justify-center xl:w-[264px] xl:justify-start xl:pl-3">
          <Logo wordmark={false} className="sm:hidden" />
          <Logo className="hidden sm:flex lg:hidden xl:flex" />
          <Logo wordmark={false} className="hidden lg:flex xl:hidden" />
        </Link>
        <div className="min-w-0 flex-1 sm:flex-none lg:ml-2">
          <AccountSwitcher />
        </div>
        {/* Phones: DEMO/LIVE above "● Running/Stopped" in one narrow column; wider screens lay them out in the row. */}
        <div className="flex shrink-0 flex-col items-center gap-1 sm:contents">
          <ModePill />
          <BotStatus className="sm:order-2" />
        </div>
        <div className="hidden flex-1 sm:order-1 sm:block" />
        <TradingToggle className="sm:order-3" />
        <Button variant="ghost" size="icon-lg" asChild className="relative hidden sm:order-4 sm:inline-flex">
          <Link href="/settings?tab=notifications" aria-label={`Notifications (${unread} unread)`}>
            <Bell aria-hidden />
            {unread > 0 && <span className="absolute top-2 right-2 size-2.5 rounded-full bg-primary ring-2 ring-background lg:ring-shell" aria-hidden />}
          </Link>
        </Button>
        <ThemeToggle className="hidden sm:order-5 sm:inline-flex" />
        <div className="relative shrink-0 sm:order-6">
          <UserMenu unread={unread} />
          {unread > 0 && <span className="pointer-events-none absolute -top-0.5 -right-0.5 size-3 rounded-full bg-primary ring-2 ring-background sm:hidden" aria-hidden />}
        </div>
      </div>
    </header>
  );
}

function UserMenu({ unread }: { unread: number }) {
  const { user, logout } = useSession();
  const { preference, setPreference } = useTheme();
  const initials = user.name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger aria-label="Account menu"
        className="touch-hit flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-hover p-1 transition-transform hover:scale-105 dark:bg-[#1f1f1f]">
        <span className="flex size-full items-center justify-center rounded-full bg-brand text-[11px] font-extrabold text-white">{initials}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <p className="truncate text-sm font-medium text-fg">{user.name}</p>
          <p className="truncate text-xs text-fg-subtle">{user.email}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-fg-subtle">Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={preference} onValueChange={(v) => isThemePreference(v) && setPreference(v)}>
          <DropdownMenuRadioItem value="system"><Monitor aria-hidden /> System</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light"><Sun aria-hidden /> Light</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark"><Moon aria-hidden /> Dark</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        {/* Phones: the bell lives here instead of the top bar. */}
        <DropdownMenuItem asChild className="sm:hidden">
          <Link href="/settings?tab=notifications">
            <Bell aria-hidden /> Notifications
            {unread > 0 && <span className="num ml-auto rounded-full bg-primary px-2 py-0.5 text-xs font-bold text-primary-foreground">{unread}<span className="sr-only"> unread</span></span>}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/settings"><Settings aria-hidden /> Settings</Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void logout()}>
          <LogOut aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
