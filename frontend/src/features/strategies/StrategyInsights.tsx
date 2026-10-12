"use client";

import { ChevronDown, ChevronRight, OctagonX, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { Notice } from "@/components/app/states";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { GroupTable, ValidationCard } from "@/features/backtesting/BacktestReport";
import { api } from "@/lib/api";
import { formatDateTime, formatNumber, formatPct, formatRelative, formatSignedCurrency } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Evaluation, Paginated, Signal, Strategy } from "@/lib/types";
import { allowedFamilies, allowedSymbols, contractSupportText, decisionOf, parameterRows, REGIME_LABEL, REGIME_TONE, regimeOf, riskCaps } from "./insights";
import { cn } from "@/lib/utils";
import { latestVersion } from "./strategyUtils";

/**
 * The facts behind a code strategy: where it may run, its parameters and risk
 * caps, the latest completed decision with the market regime, backtest results
 * by market and by regime with the demo-forward-testing gate — and, for admins,
 * the emergency stop on new entries. Nothing here enables or switches anything.
 */
export function StrategyInsights({ strategy: s, onChanged }: { strategy: Strategy; onChanged?: () => void }) {
  const { isAdmin } = useSession();
  const families = allowedFamilies(s);
  const symbols = allowedSymbols(s);
  const params = (latestVersion(s)?.parameters ?? {}) as Record<string, unknown>;
  const caps = riskCaps(params);
  const rows = parameterRows(s);
  const watched = s.assignments.find((a) => a.status === "ENABLED") ?? s.assignments[0] ?? null;
  const tested = s.backtests_by_symbol ?? (s.backtest ? [s.backtest] : []);
  const stop = s.entries_disabled ?? null;
  const lastRun = s.assignments.map((a) => a.last_signal_at).filter(Boolean).sort().at(-1) ?? null;

  const gate = tested.find((b) => b.validation)?.validation ?? null;
  const qualifies = tested.length > 0 && tested.every((b) => !b.validation || b.validation.qualifies_for_demo_forward_testing) && gate !== null;

  return (
    <div className="space-y-3">
      {stop && (
        <Notice tone="danger" title="New trades are stopped by an administrator">
          {stop.reason ?? "No reason given."}{stop.inherited ? " (set on the built-in this copy comes from)" : ""} Open positions are not closed.
        </Notice>
      )}
      <dl className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Stat label="Markets" className="col-span-2 lg:col-span-2">{symbols ? symbols.join(", ") : "Any market"}</Stat>
        <Stat label="Status">{stop ? <Pill tone="negative" dot>Entries stopped</Pill> : <Pill tone="positive" dot>Entries allowed</Pill>}</Stat>
        <Stat label="Last trade idea">{lastRun ? `${formatRelative(lastRun)}` : "None yet"}</Stat>
        <Stat label="Contracts" className="col-span-2 lg:col-span-4">{contractSupportText(families)}</Stat>
      </dl>

      {watched && <LatestDecision assignmentId={watched.id} symbol={watched.symbol} />}

      {caps.length > 0 && (
        <section aria-label="Risk caps" className="rounded-md bg-surface-raised px-3.5 py-3">
          <h4 className="text-xs font-semibold text-fg-subtle">Risk caps <span className="font-normal">— they only tighten your risk profile</span></h4>
          <ul className="mt-1.5 divide-y divide-line text-[13px]">
            {caps.map((c) => (
              <li key={c.key} className="flex items-baseline justify-between gap-3 py-1.5">
                <span className="min-w-0 text-fg-muted">{c.label}</span>
                <span className="num shrink-0 font-bold text-fg">{c.value}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {rows.length > 0 && (
        <Collapsible title="Parameters" meta={String(rows.length)}>
          <dl className="divide-y divide-line">
            {rows.map((r) => (
              <div key={r.key} className="py-2 first:pt-0 last:pb-0">
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="min-w-0 text-[13px] font-semibold break-words text-fg">{r.label}</dt>
                  <dd className="num shrink-0 text-[13px] font-bold text-fg">{r.value}</dd>
                </div>
                {r.description && <p className="mt-0.5 text-xs leading-snug text-fg-subtle">{r.description}</p>}
              </div>
            ))}
          </dl>
        </Collapsible>
      )}

      {tested.length > 0 && (
        <Collapsible
          title="Tests on history"
          meta={`${tested.length} ${tested.length === 1 ? "market" : "markets"}`}
          badge={gate ? <Pill tone={qualifies ? "positive" : "warning"}>{qualifies ? "Qualifies" : "Not validated"}</Pill> : null}
        >
          <p className="text-xs text-fg-subtle">Latest test on each market. Tap one for the full report.</p>
          <ul className="space-y-2.5" aria-label="Tests on history by market">
            {tested.map((b) => (
              <li key={b.id} className="rounded-md bg-surface-raised p-3">
                <Link href={`/strategies/backtests/${b.id}`} className="group/bt flex min-h-11 items-center justify-between gap-2 rounded-sm">
                  <span className="flex min-w-0 flex-wrap items-center gap-2 font-bold text-fg">
                    <span className="break-all group-hover/bt:underline">{b.symbol} {b.timeframe}</span>
                    {b.data_source === "synthetic" && <Pill tone="warning">Synthetic</Pill>}
                  </span>
                  <ChevronRight className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                </Link>
                <dl className="mt-1 grid grid-cols-3 gap-x-3 gap-y-2 text-xs">
                  <MiniStat label="Trades">{b.trades ?? 0}</MiniStat>
                  <MiniStat label="Wins">{formatPct(b.win_rate, 0)}</MiniStat>
                  <MiniStat label="Profit factor">{b.profit_factor == null ? "—" : formatNumber(b.profit_factor)}</MiniStat>
                  <MiniStat label="Per trade">{b.expectancy == null ? "—" : formatSignedCurrency(b.expectancy, "USD")}</MiniStat>
                  <MiniStat label="Drawdown">{formatPct(b.max_drawdown_pct, 1)}</MiniStat>
                </dl>
                {b.validation && <div className="mt-3 border-t border-line pt-3"><ValidationCard v={b.validation} compact /></div>}
              </li>
            ))}
          </ul>
        </Collapsible>
      )}

      {s.backtest?.by_regime && s.backtest.by_regime.length > 0 && (
        <Collapsible title="Results by market regime" meta="latest test">
          <p className="text-xs text-fg-subtle">The regime when each trade was taken (closed candles only).</p>
          <GroupTable groups={s.backtest.by_regime} currency="USD" label="Regime" />
        </Collapsible>
      )}

      {isAdmin && <EmergencyStop strategy={s} onChanged={onChanged} />}
    </div>
  );
}

/** One fact in the overview grid. */
function Stat({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0 rounded-md bg-surface-raised px-3 py-2.5", className)}>
      <dt className="text-xs font-semibold text-fg-subtle">{label}</dt>
      <dd className="mt-1 text-[13px] leading-snug font-semibold break-words text-fg">{children}</dd>
    </div>
  );
}

function MiniStat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-fg-subtle">{label}</dt>
      <dd className="num mt-0.5 truncate text-[13px] font-bold text-fg">{children}</dd>
    </div>
  );
}

/** A section that folds away (native <details>: keyboard and screen-reader friendly, no state). */
function Collapsible({ title, meta, badge, defaultOpen, children }: { title: string; meta?: string; badge?: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode }) {
  return (
    <details open={defaultOpen} className="group/fold rounded-md ring-1 ring-line">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-md px-3.5 py-2.5 transition-colors hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1 text-sm font-bold text-fg">
          {title}{meta && <span className="ml-2 text-xs font-semibold text-fg-subtle">{meta}</span>}
        </span>
        {badge}
        <ChevronDown className="size-4 shrink-0 text-fg-subtle transition-transform group-open/fold:rotate-180" aria-hidden />
      </summary>
      <div className="space-y-3 border-t border-line px-3.5 py-3">{children}</div>
    </details>
  );
}

function LatestDecision({ assignmentId, symbol }: { assignmentId: string; symbol: string }) {
  const data = useApi<{ evaluations: Paginated<Evaluation>; signals: Signal[] }>(`/assignments/${assignmentId}/evaluations`, { per_page: 1 }, 60_000);
  const e = data.data?.evaluations.data[0] ?? null;
  if (!data.data) return null;
  if (!e) return <p className="rounded-md px-3.5 py-3 text-xs text-fg-muted ring-1 ring-line">No completed candle checked on {symbol} yet.</p>;
  const decision = decisionOf(e);
  const regime = regimeOf(e);
  return (
    <section aria-label="Latest signal" className="rounded-md p-3.5 ring-1 ring-line">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-xs font-semibold text-fg-subtle">Latest signal</h4>
        <Pill tone={decision === "BUY" ? "positive" : decision === "SELL" ? "negative" : "neutral"}>{decision === "NO_TRADE" ? "No trade" : decision}</Pill>
        {regime && <Pill tone={REGIME_TONE[regime.regime]}>{REGIME_LABEL[regime.regime]}</Pill>}
      </div>
      <p className="mt-2 text-sm leading-snug break-words text-fg">{e.summary}</p>
      {regime && <p className="mt-1 text-xs leading-snug break-words text-fg-muted">Regime: {regime.reason}</p>}
      <p className="mt-1.5 text-xs text-fg-subtle">Closed candle on {symbol} · {formatDateTime(e.bar_time)}</p>
    </section>
  );
}

/** Admins: stop or allow NEW entries from this strategy for everyone (audited; never closes positions). */
function EmergencyStop({ strategy: s, onChanged }: { strategy: Strategy; onChanged?: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const action = useAction();
  const own = s.entries_disabled && !s.entries_disabled.inherited;
  const submit = async () => {
    const res = await action.run(() => api(`/admin/strategies/${s.id}/${own ? "enable" : "disable"}`, { method: "POST", body: own ? { confirm: true } : { reason } }));
    if (res) {
      setOpen(false);
      setReason("");
      toast.success(own ? `${s.name} may open trades again` : `New trades from ${s.name} are stopped`);
      onChanged?.();
    }
  };
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
      <p className="text-xs text-fg-muted">Admin · strategy emergency stop (for every user; open positions are never closed)</p>
      <Button size="sm" variant={own ? "outline" : "destructive"} className="max-sm:w-full" onClick={() => { action.reset(); setOpen(true); }}>
        {own ? <><ShieldCheck aria-hidden /> Allow new entries</> : <><OctagonX aria-hidden /> Stop new entries…</>}
      </Button>
      <ConfirmDialog open={open} onOpenChange={setOpen} destructive={!own} busy={action.busy} error={action.error}
        title={own ? `Allow ${s.name} to open trades again?` : `Stop new trades from ${s.name}?`}
        confirmLabel={own ? "Allow new entries" : "Stop new entries"}
        onConfirm={() => { if (own || reason.trim().length > 0) void submit(); }}>
        {own ? (
          <p>Every other rule — risk limits, STOP switches, the platform halt — still applies.</p>
        ) : (
          <div className="space-y-2">
            <p>Nobody&apos;s accounts will open new trades from this strategy (or from copies of it). Open positions keep their stop and target.</p>
            <Label htmlFor={`stop-reason-${s.id}`}>Reason (shown to users and kept in the audit log)</Label>
            <Textarea id={`stop-reason-${s.id}`} value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
