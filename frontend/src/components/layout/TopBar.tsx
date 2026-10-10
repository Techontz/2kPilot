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
    <header className="sticky top-0 z-30 border-b border-line/60 bg-[color-mix(in_oklab,var(--background)_85%,transparent)] backdrop-blur-xl backdrop-saturate-150 lg:border-b-0 lg:bg-shell lg:backdrop-blur-none">
      <div className="flex h-16 items-center gap-2 px-3 sm:gap-3 sm:px-5 lg:px-2 lg:pr-4">
        <Link href="/" aria-label="2kPilot home" className="hidden shrink-0 rounded-lg min-[420px]:block lg:flex lg:w-[76px] lg:justify-center xl:w-[264px] xl:justify-start xl:pl-3">
          <Logo wordmark={false} className="sm:hidden" />
          <Logo className="hidden sm:flex lg:hidden xl:flex" />
          <Logo wordmark={false} className="hidden lg:flex xl:hidden" />
        </Link>
        <div className="min-w-0 flex-1 sm:flex-none lg:ml-2">
          <AccountSwitcher />
        </div>
        <ModePill />
        <div className="hidden flex-1 sm:block" />
        <BotStatus />
        <TradingToggle />
        <Button variant="ghost" size="icon-lg" asChild className="relative hidden sm:inline-flex">
          <Link href="/settings?tab=notifications" aria-label={`Notifications (${unread} unread)`}>
            <Bell aria-hidden />
            {unread > 0 && <span className="absolute top-2 right-2 size-2.5 rounded-full bg-primary ring-2 ring-background lg:ring-shell" aria-hidden />}
          </Link>
        </Button>
        <ThemeToggle className="hidden sm:inline-flex" />
        <UserMenu />
      </div>
    </header>
  );
}

function UserMenu() {
  const { user, logout } = useSession();
  const { preference, setPreference } = useTheme();
  const initials = user.name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger aria-label="Account menu"
        className="flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-hover p-1 transition-transform hover:scale-105 dark:bg-[#1f1f1f]">
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
