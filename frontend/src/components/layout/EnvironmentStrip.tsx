"use client";

import { AlertOctagon, ShieldAlert, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useAppData } from "../providers/AppDataProvider";
import { useSession } from "../providers/SessionProvider";

/**
 * Banners under the top bar: a loud strip for a LIVE (real money) account, the
 * platform-wide admin halt, an offline engine and the MFA nudge. DEMO/LIVE mode
 * itself is always shown by the pill in the top bar.
 */
export function EnvironmentStrip() {
  const { account, status } = useAppData();
  const { user } = useSession();
  return (
    <>
      {account?.environment === "LIVE" && (
        <div role="alert" className="flex items-center justify-center gap-2 bg-live px-4 py-2 text-center text-xs font-extrabold tracking-[0.14em] text-live-foreground">
          <AlertOctagon className="size-4" aria-hidden /> LIVE ACCOUNT — REAL MONEY
        </div>
      )}
      {(status?.platform_halted || status?.engine_state === "offline" || !user.mfa_enabled) && (
        <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-2 px-4 pt-4 sm:px-6 lg:px-8">
          {status?.platform_halted && (
            <div role="alert" className="flex items-start gap-3 rounded-lg border border-negative/30 bg-negative-soft px-4 py-3 text-sm text-fg backdrop-blur">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-negative text-negative-foreground"><AlertOctagon className="size-4" aria-hidden /></span>
              <p className="min-w-0 self-center"><span className="font-bold text-negative">Trading is halted platform-wide by an administrator</span> — no new orders for anyone.{status.platform_halt_reason && ` Reason: ${status.platform_halt_reason}`}</p>
            </div>
          )}
          {status?.engine_state === "offline" && (
            <div className="flex items-start gap-3 rounded-lg border border-negative/30 bg-negative-soft px-4 py-3 text-sm text-fg backdrop-blur">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-negative text-negative-foreground"><ShieldAlert className="size-4" aria-hidden /></span>
              <p className="min-w-0 self-center"><span className="font-bold text-negative">The trading engine is offline</span> — no automated trading. {status.engine_detail}</p>
            </div>
          )}
          {!user.mfa_enabled && (
            <div className="flex items-center gap-3 rounded-2xl sm:rounded-full bg-[color-mix(in_oklab,var(--card)_70%,transparent)] py-1.5 pr-4 pl-1.5 text-sm text-fg-muted ring-1 ring-warning/30 backdrop-blur">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-warning-soft text-warning"><ShieldCheck className="size-4" aria-hidden /></span>
              <span className="min-w-0">Protect this account: <Link href="/settings?tab=security" className="font-semibold text-fg underline decoration-warning/60 underline-offset-4 hover:decoration-warning">turn on two-factor authentication</Link>.</span>
            </div>
          )}
        </div>
      )}
    </>
  );
}
