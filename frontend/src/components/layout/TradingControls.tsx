"use client";

import { Play, Square } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import { deriveRobotStatus, MODE_INFO } from "@/lib/status";
import { resumeTrading, stopTrading } from "@/lib/tradingActions";
import type { TradingStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAppData } from "../providers/AppDataProvider";

const DOT = { positive: "bg-positive", warning: "bg-warning", negative: "bg-negative", neutral: "bg-fg-subtle", live: "bg-live", info: "bg-info" };

interface TradingControl {
  /** Stop is ONE click — never confirmed, retried until it gets through. */
  stop: () => Promise<void>;
  /** Start asks for confirmation first (opens the dialog). */
  requestStart: () => void;
  /** A stop request is in flight. */
  busy: boolean;
}

const TradingControlContext = createContext<TradingControl | null>(null);

/** What the Start dialog is confirming: the status fetched when it opened (never a stale copy). */
interface Confirming {
  status: TradingStatus | null;
  checking: boolean;
}

/**
 * One Start/Stop implementation for the top bar and the big Home button, with
 * one shared confirmation dialog. Stop never asks; Start explains what will
 * happen (mode, virtual vs real money, engine/halt warnings) and asks once.
 *
 * The dialog's wording comes from a status fetched as it opens, and starting
 * in LIVE sends `live: true`: the server refuses LIVE without it, so a dialog
 * that said "Demo" can never start real-money trading. Every response carries
 * the full status, which is shown at once.
 */
export function TradingControlProvider({ children }: { children: ReactNode }) {
  const { reloadStatus, setStatus } = useAppData();
  const [confirming, setConfirming] = useState<Confirming | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);

  const stop = useCallback(async () => {
    setStopping(true);
    try {
      setStatus(await stopTrading("Stopped from the dashboard"));
      toast.success("Trading stopped", { description: "No new trades will open. Open trades stay open until they finish." });
    } catch (error) {
      toast.error("Could not stop trading", {
        description: `${error instanceof ApiError ? error.message : "The server did not answer."} Press Stop again — it is always safe.`,
        duration: 15_000,
      });
    } finally {
      setStopping(false);
    }
  }, [setStatus]);

  const requestStart = useCallback(() => {
    setStartError(null);
    setConfirming({ status: null, checking: true });
    void reloadStatus().then((fresh) => {
      setConfirming((open) => (open ? { status: fresh, checking: false } : open));
      if (!fresh) setStartError("Can't check your trading status right now. Wait a moment and try again.");
    });
  }, [reloadStatus]);

  const shown = confirming?.status ?? null;
  const live = shown?.trading_mode === "LIVE";

  const start = async () => {
    if (!shown) return;
    setStarting(true);
    setStartError(null);
    try {
      const next = await resumeTrading(live);
      setStatus(next);
      setConfirming(null);
      toast.success("Trading started", { description: `Active strategies may now trade in ${MODE_INFO[next.trading_mode].label} mode.` });
    } catch (error) {
      if (error instanceof ApiError && error.code === "live_confirmation_required") {
        // The mode changed since this dialog opened: show the LIVE wording and ask again.
        const fresh = await reloadStatus();
        setConfirming({ status: fresh, checking: false });
        setStartError("Your trading is in LIVE mode now — this would use REAL money. Read the warning and confirm again.");
      } else {
        setStartError(error instanceof ApiError ? error.message : "Something went wrong.");
      }
    } finally {
      setStarting(false);
    }
  };

  return (
    <TradingControlContext.Provider value={{ stop, requestStart, busy: stopping }}>
      {children}
      <AlertDialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{!shown ? "Start trading?" : live ? "Start trading with REAL money?" : "Start trading in Demo?"}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2">
                {!shown ? (
                  confirming?.checking && <p>Checking your trading mode…</p>
                ) : (
                  <p>
                    Your active strategies may open trades
                    {live ? <strong className="text-live"> on LIVE accounts with real money.</strong> : <> on Paper and demo accounts — <strong className="text-fg">virtual money only</strong>.</>}{" "}
                    Every trade still passes your risk limits. It keeps running on the server after you close this page, until you press Stop.
                  </p>
                )}
                {shown?.engine_state === "offline" && <p className="text-warning">The trading engine is offline, so nothing will trade until it is running again.</p>}
                {shown?.platform_halted && <p className="text-warning">An administrator has paused trading for everyone. Nothing will trade until it is resumed.</p>}
                {startError && <p role="alert" className="text-negative">{startError}</p>}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <Button onClick={() => void start()} disabled={starting || !shown}
              className={cn("font-bold", live ? "bg-live text-live-foreground hover:bg-live/90" : "bg-positive text-positive-foreground hover:bg-positive/90")}>
              {starting ? "Starting…" : live ? "Start with real money" : "Start trading"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </TradingControlContext.Provider>
  );
}

export function useTradingControl(): TradingControl {
  const value = useContext(TradingControlContext);
  if (!value) throw new Error("useTradingControl must be used inside TradingControlProvider");
  return value;
}

const UNKNOWN_LABEL = "Status unknown — reconnecting";

/** "Is my bot running?" — a dot always, the words from md up. */
export function BotStatus() {
  const { status, statusUnknown } = useAppData();
  if (!status && !statusUnknown) return null;
  const robot = !status || statusUnknown
    ? { label: UNKNOWN_LABEL, tone: "neutral" as const, running: false, detail: "Can't reach the server for the latest status. Stop still works." }
    : deriveRobotStatus(status);
  const label = !status || statusUnknown ? "Unknown" : robot.running ? "Running" : "Stopped";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="flex h-9 shrink-0 items-center gap-2 rounded-full px-1.5 text-sm font-semibold text-fg md:bg-surface-hover md:px-3 md:dark:bg-[#1f1f1f]" role="status" aria-live="polite" aria-label={`Bot: ${robot.label}`} tabIndex={0}>
          <span className="relative flex size-2.5" aria-hidden>
            {robot.running && <span className={cn("absolute inset-0 rounded-full motion-safe:animate-pulse-ring", DOT[robot.tone])} />}
            <span className={cn("relative size-2.5 rounded-full", DOT[robot.tone])} />
          </span>
          <span className="hidden md:inline">{label}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="block max-w-64">
        <p className="font-medium">{robot.label}</p>
        <p className="opacity-80">{robot.detail}</p>
      </TooltipContent>
    </Tooltip>
  );
}

/** Start only when the status is known and trading is stopped; otherwise Stop (always safe). */
function showsStart(status: TradingStatus | null, unknown: boolean): boolean {
  return status !== null && !unknown && status.kill_switch_engaged;
}

/** Compact Start / Stop in the top bar (always visible). */
export function TradingToggle() {
  const { status, statusUnknown } = useAppData();
  const { stop, requestStart, busy } = useTradingControl();
  return showsStart(status, statusUnknown) ? (
    <Button size="lg" onClick={requestStart} aria-label="Start trading" className="shrink-0 bg-positive px-3.5 font-bold text-positive-foreground hover:bg-positive/90 sm:px-5">
      <Play aria-hidden className="fill-current" />
      <span className="hidden sm:inline">Start</span>
    </Button>
  ) : (
    <Button size="lg" variant="outline" onClick={() => void stop()} disabled={busy} aria-label="Stop trading"
      className="shrink-0 border-negative/60 px-3.5 font-bold text-negative hover:border-negative hover:bg-negative-soft hover:text-negative sm:px-5 dark:border-negative/60 dark:hover:border-negative">
      <Square aria-hidden className="fill-current" />
      <span className="hidden sm:inline">{busy ? "Stopping…" : "Stop"}</span>
    </Button>
  );
}

/** The big Start / Stop on Home. */
export function BigTradingButton({ className }: { className?: string }) {
  const { status, statusUnknown } = useAppData();
  const { stop, requestStart, busy } = useTradingControl();
  return showsStart(status, statusUnknown) ? (
    <Button size="lg" onClick={requestStart} className={cn("h-14 w-full gap-3 bg-positive pr-7 pl-2 text-base font-bold text-positive-foreground shadow-[0_10px_28px_-10px_var(--positive)] hover:scale-[1.02] hover:bg-positive/90", className)}>
      <span className="flex size-10 items-center justify-center rounded-full bg-black/15" aria-hidden><Play className="size-5! translate-x-px fill-current" /></span> Start trading
    </Button>
  ) : (
    <Button size="lg" variant="outline" onClick={() => void stop()} disabled={busy}
      className={cn("h-14 w-full gap-3 border-2 border-negative pr-7 pl-2 text-base font-bold text-negative hover:bg-negative-soft hover:text-negative dark:border-negative", className)}>
      <span className="flex size-10 items-center justify-center rounded-full bg-negative text-negative-foreground" aria-hidden><Square className="size-4! fill-current" /></span> {busy ? "Stopping…" : "Stop trading"}
    </Button>
  );
}
