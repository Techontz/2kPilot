"use client";

import { Pill } from "@/components/app/badges";
import { ErrorState, ListSkeleton } from "@/components/app/states";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Checks } from "@/features/history/TradeDetailSheet";
import { formatDateTime, formatRelative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Assignment, Evaluation, Paginated, Signal } from "@/lib/types";

const OUTCOME = { SIGNAL: { label: "Signal", tone: "positive" }, NO_SETUP: { label: "No setup", tone: "neutral" }, INSUFFICIENT_DATA: { label: "Not enough data yet", tone: "warning" } } as const;
const SIGNAL_TONE: Record<string, "positive" | "warning" | "negative" | "neutral"> = { EXECUTED: "positive", REJECTED: "warning", FAILED: "negative" };

/** "Why no trade?" — every closed candle the strategy checked, and what the risk limits said. */
export function EvaluationsSheet({ assignment, onClose }: { assignment: Assignment | null; onClose: () => void }) {
  const data = useApi<{ evaluations: Paginated<Evaluation>; signals: Signal[] }>(assignment ? `/assignments/${assignment.id}/evaluations` : null, undefined, 10_000);
  const d = data.data;
  return (
    <Sheet open={assignment !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-lg">
        <SheetHeader className="border-b border-line">
          <SheetTitle>Why {assignment?.symbol} did — or didn&apos;t — trade</SheetTitle>
          <SheetDescription>The rules are checked each time a candle closes. Trades the rules wanted but your risk limits refused are listed with the reason.</SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-8">
          {data.error && !d ? <ErrorState message={data.error} onRetry={() => void data.reload()} /> : !d ? <ListSkeleton rows={4} /> : (
            <>
              <section>
                <h3 className="mb-2 text-sm font-semibold text-fg">Trade ideas and risk decisions</h3>
                {d.signals.length === 0 ? <p className="text-sm text-fg-muted">No trade ideas yet — the rules haven&apos;t matched.</p> : (
                  <ul className="space-y-2">
                    {d.signals.map((s) => (
                      <li key={s.id} className="rounded-lg border border-line px-3 py-2 text-sm">
                        <p className="flex items-center justify-between gap-2">
                          <span className="text-fg">{s.side === "BUY" ? "Up" : "Down"} · candle {formatDateTime(s.bar_time)}</span>
                          <Pill tone={SIGNAL_TONE[s.status] ?? "neutral"}>{s.status === "EXECUTED" ? "Traded" : s.status === "REJECTED" ? "Refused by limits" : s.status.toLowerCase()}</Pill>
                        </p>
                        <p className="mt-1 text-xs text-fg-muted">{s.rejection_reason ?? s.reasons.join("; ")}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section>
                <h3 className="mb-2 text-sm font-semibold text-fg">Every closed candle</h3>
                {d.evaluations.data.length === 0 ? (
                  <p className="text-sm text-fg-muted">No candles checked yet. Checks happen while trading is started and the strategy is active.</p>
                ) : (
                  <ul className="space-y-3">
                    {d.evaluations.data.map((e) => (
                      <li key={e.id} className="rounded-lg border border-line px-3 py-2.5">
                        <p className="flex items-center justify-between gap-2">
                          <span className="num text-xs text-fg-subtle">{formatDateTime(e.bar_time)} · {formatRelative(e.bar_time)}</span>
                          <Pill tone={OUTCOME[e.outcome].tone}>{OUTCOME[e.outcome].label}</Pill>
                        </p>
                        <p className="mt-1 text-sm text-fg">{e.summary}</p>
                        {e.checks.length > 0 && <div className="mt-2"><Checks items={e.checks.map((c) => ({ rule: c.name, passed: c.passed, detail: c.detail }))} /></div>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
