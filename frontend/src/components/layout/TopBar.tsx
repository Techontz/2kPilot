"use client";

import { LogOut, Menu } from "lucide-react";
import Link from "next/link";
import { useSession } from "@/components/providers/SessionProvider";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { deriveRobotStatus } from "@/lib/status";
import { KillSwitchButton } from "./KillSwitchButton";
import { ModeBadge } from "./ModeBadge";

export function TopBar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { user, logout } = useSession();
  const { status, error } = useSystemStatus();
  const robot = status ? deriveRobotStatus(status.trading) : null;

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-canvas/90 px-4 backdrop-blur lg:px-6">
      <button
        type="button"
        onClick={onOpenMenu}
        className="rounded-md p-1.5 text-fg-muted hover:bg-surface-raised lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="size-5" />
      </button>

      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 sm:gap-2">
        {status && <ModeBadge mode={status.trading.trading_mode} />}
        {robot && (
          <Link href="/risk" title={robot.detail}>
            <Badge tone={robot.tone} dot>
              {robot.label}
            </Badge>
          </Link>
        )}
        {error && !status && (
          <Badge tone="negative" dot>
            Server unreachable
          </Badge>
        )}
      </div>

      <KillSwitchButton size="sm" />

      <div className="ml-1 hidden items-center gap-2 border-l border-line pl-3 sm:flex">
        <span className="max-w-40 truncate text-sm text-fg-muted" title={user.email}>
          {user.display_name}
        </span>
        <Button variant="ghost" size="sm" onClick={() => void logout()} aria-label="Sign out">
          <LogOut aria-hidden className="size-4" />
        </Button>
      </div>
    </header>
  );
}
