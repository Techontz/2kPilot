"use client";

import { ChevronDown, ShieldAlert, ShieldCheck, WifiOff } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { RealMoneyDialog } from "@/features/settings/RealMoneyDialog";
import { ApiError } from "@/lib/api";
import { MODE_INFO } from "@/lib/status";
import { returnToDemo } from "@/lib/tradingActions";
import { cn } from "@/lib/utils";
import { useAppData } from "../providers/AppDataProvider";

/** The always-visible DEMO / LIVE indicator — and the door to real money (or back). */
export function ModePill() {
  const { status, statusUnknown, reloadStatus, setStatus } = useAppData();
  const [dialog, setDialog] = useState(false);
  const [busy, setBusy] = useState(false);
  if (statusUnknown) {
    // Never show a last-known DEMO/LIVE that may be wrong.
    return (
      <span role="status" aria-label="Status unknown — reconnecting" title="Status unknown — reconnecting"
        className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full bg-muted px-3 text-xs font-bold text-fg-muted ring-1 ring-line max-sm:h-7 max-sm:px-2.5 max-sm:text-[11px]">
        <WifiOff className="size-3" aria-hidden />
        <span className="hidden min-[420px]:inline">Reconnecting…</span>
      </span>
    );
  }
  if (!status) return null;
  const mode = status.trading_mode;
  const live = mode === "LIVE";
  const revoked = !live ? status.live_revoked_reason : null;

  const toDemo = async () => {
    setBusy(true);
    try {
      setStatus(await returnToDemo());
      toast.success("Back in Demo mode", { description: "Real-money trading is off. Trading is stopped — press Start to trade with virtual money." });
    } catch (error) {
      toast.error("Could not return to Demo", { description: error instanceof ApiError ? error.message : "Try again." });
      await reloadStatus();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={live ? "LIVE mode — real money. Change mode" : "Demo mode — virtual money. Change mode"}
          className={cn(
            "touch-hit inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-xs font-extrabold tracking-[0.12em] outline-none transition-transform hover:scale-[1.03] focus-visible:ring-3 focus-visible:ring-ring/50 max-sm:h-7 max-sm:px-2.5 max-sm:text-[11px]",
            live ? "bg-live text-live-foreground shadow-[0_0_0_3px_color-mix(in_oklab,var(--live)_30%,transparent),0_6px_20px_-6px_var(--live)]" : "bg-transparent text-demo ring-1 ring-demo/55 hover:bg-demo-soft",
          )}
        >
          {live ? <span className="size-1.5 rounded-full bg-live-foreground motion-safe:animate-pulse" aria-hidden /> : <span className="size-1.5 rounded-full bg-demo" aria-hidden />}
          {live ? "LIVE" : "DEMO"}
          <ChevronDown className="hidden size-3 opacity-70 min-[420px]:block" aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuLabel className="space-y-1 font-normal">
            <span className={cn("block text-sm font-semibold", live ? "text-live" : "text-demo")}>{live ? "LIVE — real money" : "Demo — virtual money"}</span>
            <span className="block text-xs text-fg-muted">{MODE_INFO[mode].explanation}</span>
            {revoked && <span role="note" className="block text-xs text-warning">{revoked}</span>}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {live ? (
            <DropdownMenuItem disabled={busy} onSelect={() => void toDemo()}>
              <ShieldCheck aria-hidden /> Return to Demo
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onSelect={() => setDialog(true)}>
              <ShieldAlert aria-hidden /> Authorize real-money trading…
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <RealMoneyDialog open={dialog} onOpenChange={setDialog} />
    </>
  );
}
