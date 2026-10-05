"use client";

import { AlertOctagon, FlaskConical, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useAppData } from "../providers/AppDataProvider";
import { useSession } from "../providers/SessionProvider";

/** A thin, unmistakable strip: PAPER (simulated), DEMO (virtual money) or LIVE (real money). */
export function EnvironmentStrip() {
  const { account, status } = useAppData();
  const { user } = useSession();
  return (
    <>
      {account?.environment === "LIVE" && (
        <div role="alert" className="flex items-center justify-center gap-2 bg-live px-4 py-1.5 text-center text-xs font-bold tracking-wider text-white">
          <AlertOctagon className="size-4" aria-hidden /> LIVE ACCOUNT — REAL MONEY
        </div>
      )}
      {account?.environment === "PAPER" && (
        <div className="flex items-center justify-center gap-2 border-b border-line bg-surface px-4 py-1 text-center text-xs text-fg-muted">
          <FlaskConical className="size-3.5" aria-hidden /> PAPER account — simulated prices and fills. No real money.
        </div>
      )}
      {account?.environment === "DEMO" && (
        <div className="flex items-center justify-center gap-2 border-b border-info/20 bg-info-soft px-4 py-1 text-center text-xs text-info">
          DEMO account — real broker, virtual money.
        </div>
      )}
      {status?.engine_state === "offline" && (
        <div className="flex items-center justify-center gap-2 border-b border-negative/30 bg-negative-soft px-4 py-1.5 text-center text-xs text-negative">
          <ShieldAlert className="size-3.5" aria-hidden /> The trading engine is offline — no automated trading. {status.engine_detail}
        </div>
      )}
      {!user.mfa_enabled && (
        <div className="flex items-center justify-center gap-2 border-b border-warning/20 bg-warning-soft px-4 py-1 text-center text-xs text-warning">
          Protect this account: <Link href="/settings#security" className="underline underline-offset-2">turn on two-factor authentication</Link>.
        </div>
      )}
    </>
  );
}
