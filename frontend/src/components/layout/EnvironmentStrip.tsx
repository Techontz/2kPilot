"use client";

import { AlertOctagon, Info, ShieldAlert, ShieldCheck, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useAppData } from "../providers/AppDataProvider";
import { useSession } from "../providers/SessionProvider";
import { engineHealthView, type Tone } from "@/lib/status";

/** Banner styling per engine tone: offline/error is loud, a disabled supervisor is calm. */
const ENGINE_BANNER: Partial<Record<Tone, { box: string; badge: string; text: string; Icon: typeof Info }>> = {
  negative: { box: "border-negative/30 bg-negative-soft", badge: "bg-negative text-negative-foreground", text: "text-negative", Icon: ShieldAlert },
  warning: { box: "border-warning/30 bg-warning-soft", badge: "bg-warning text-warning-foreground", text: "text-warning", Icon: TriangleAlert },
  info: { box: "border-border bg-[color-mix(in_oklab,var(--card)_70%,transparent)]", badge: "bg-[color-mix(in_oklab,var(--brand-ink)_16%,transparent)] text-brand-ink", text: "text-fg", Icon: Info },
};

/**
 * Banners under the top bar: a loud strip for a LIVE (real money) account, the
 * platform-wide admin halt, the trading engine's health (offline only when its
 * API cannot be reached; a disabled or stale supervisor is described as such)
 * and the MFA nudge. DEMO/LIVE mode
 * itself is always shown by the pill in the top bar.
 */
export function EnvironmentStrip() {
  const { account, status } = useAppData();
  const { user } = useSession();
  const engine = status ? engineHealthView(status) : null;
  const engineBanner = engine?.banner ? ENGINE_BANNER[engine.tone] ?? ENGINE_BANNER.warning! : null;
  return (
    <>
      {account?.environment === "LIVE" && (
        <div role="alert" className="flex items-center justify-center gap-2 bg-live px-4 py-2 text-center text-xs font-extrabold tracking-[0.14em] text-live-foreground">
          <AlertOctagon className="size-4" aria-hidden /> LIVE ACCOUNT — REAL MONEY
        </div>
      )}
      {(status?.platform_halted || engineBanner || !user.mfa_enabled) && (
        <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-2 px-4 pt-4 sm:px-6 lg:px-8">
          {status?.platform_halted && (
            <div role="alert" className="flex items-start gap-3 rounded-lg border border-negative/30 bg-negative-soft px-4 py-3 text-sm text-fg backdrop-blur">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-negative text-negative-foreground"><AlertOctagon className="size-4" aria-hidden /></span>
              <p className="min-w-0 self-center"><span className="font-bold text-negative">Trading is halted platform-wide by an administrator</span> — no new orders for anyone.{status.platform_halt_reason && ` Reason: ${status.platform_halt_reason}`}</p>
            </div>
          )}
          {engine && engineBanner && (
            <div role={engine.tone === "negative" ? "alert" : "status"} className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm text-fg backdrop-blur ${engineBanner.box}`}>
              <span className={`flex size-7 shrink-0 items-center justify-center rounded-full ${engineBanner.badge}`}><engineBanner.Icon className="size-4" aria-hidden /></span>
              <p className="min-w-0 self-center"><span className={`font-bold ${engineBanner.text}`}>{engine.label}</span> — {engine.message}</p>
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
