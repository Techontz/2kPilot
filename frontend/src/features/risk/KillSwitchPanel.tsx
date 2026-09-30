"use client";

import { OctagonX, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { KillSwitchButton } from "@/components/layout/KillSwitchButton";
import { useSession } from "@/components/providers/SessionProvider";
import { inputClass } from "@/components/ui/inputClass";
import { Term } from "@/components/ui/Term";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import type { TradingStatus } from "@/lib/types";

export function KillSwitchPanel({ trading }: { trading: TradingStatus }) {
  const { isOwner } = useSession();
  const [reason, setReason] = useState("");
  const engaged = trading.kill_switch_engaged;

  return (
    <section
      className={cn(
        "rounded-xl border p-6",
        engaged ? "border-warning/40 bg-warning-soft" : "border-positive/30 bg-positive-soft",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="flex gap-4">
          {engaged ? (
            <OctagonX aria-hidden className="mt-0.5 size-8 shrink-0 text-warning" />
          ) : (
            <ShieldCheck aria-hidden className="mt-0.5 size-8 shrink-0 text-positive" />
          )}
          <div>
            <p className="text-xs font-medium tracking-wide text-fg-muted uppercase">
              <Term id="killSwitch" />
            </p>
            <h2 className="mt-1 text-lg font-semibold text-fg">
              {engaged ? "All trading is stopped" : "Trading is allowed"}
            </h2>
            <p className="mt-1 max-w-xl text-sm text-fg-muted">
              {engaged
                ? "No new orders can be placed and automated strategies are paused. Open positions are not closed automatically."
                : "Strategies may place new orders within the risk limits. Press STOP ALL TRADING to block everything instantly."}
            </p>
            {engaged && (
              <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
                <dt className="text-fg-subtle">Reason</dt>
                <dd className="text-fg">{trading.kill_switch_reason ?? "—"}</dd>
                <dt className="text-fg-subtle">Since</dt>
                <dd className="text-fg">{formatDateTime(trading.kill_switch_changed_at)}</dd>
              </dl>
            )}
          </div>
        </div>
        {isOwner && (
          <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-64">
            {!engaged && (
              <label className="text-xs text-fg-muted">
                Reason (optional, recorded in the audit log)
                <input
                  className={inputClass}
                  value={reason}
                  maxLength={500}
                  placeholder="e.g. High-impact news"
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            )}
            <KillSwitchButton reason={reason.trim() || undefined} />
          </div>
        )}
      </div>
    </section>
  );
}
