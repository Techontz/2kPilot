"use client";

import { ArrowRight, FlaskConical, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { PnlText } from "@/components/app/money";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { FAMILY_LABEL } from "@/lib/contracts";
import { formatDate, formatPct, formatRelative } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Backtest, Strategy } from "@/lib/types";

export function BacktestStatus({ b }: { b: Pick<Backtest, "status" | "progress"> }) {
  if (b.status === "COMPLETED") return <Pill tone="neutral">Finished</Pill>;
  if (b.status === "FAILED") return <Pill tone="negative">Failed</Pill>;
  if (b.status === "RUNNING") return <Pill tone="info" dot>Running {b.progress}%</Pill>;
  return <Pill tone="neutral" dot>Waiting to start</Pill>;
}

/** Every test you ran, newest first; running ones show progress. */
export function BacktestsList({ strategies, onTest }: { strategies: Strategy[] | null; onTest: (s: Strategy) => void }) {
  const runs = useApi<Backtest[]>("/backtests", undefined, 4000);
  const [deleting, setDeleting] = useState<Backtest | null>(null);
  const action = useAction();
  const first = strategies?.find((s) => !s.built_in) ?? null;

  const remove = async () => {
    if (!deleting) return;
    const ok = await action.run(() => api(`/backtests/${deleting.id}`, { method: "DELETE" }));
    if (ok) {
      toast.success("Test deleted");
      setDeleting(null);
      void runs.reload();
    }
  };

  if (!runs.data) return runs.error ? <ErrorState message={runs.error} onRetry={() => void runs.reload()} /> : <ListSkeleton rows={4} />;
  if (runs.data.length === 0) {
    return (
      <Card>
        <EmptyState icon={FlaskConical} title="No tests yet" action={first ? <Button onClick={() => onTest(first)}><FlaskConical aria-hidden /> Test {first.name}</Button> : <Button asChild><Link href="/strategies?tab=templates">Pick a template</Link></Button>}>
          A test replays past prices through your strategy and your risk limits, so you can see how it would have behaved — before any money is involved.
        </EmptyState>
      </Card>
    );
  }
  return (
    <ul className="space-y-3">
      {runs.data.map((b) => {
        const m = b.metrics;
        const contract = (b.config?.contract as { contract_family?: keyof typeof FAMILY_LABEL } | undefined)?.contract_family;
        return (
          <li key={b.id}>
            <Card size="sm">
              <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2">
                <div className="min-w-0 flex-1">
                  <Link href={`/strategies/backtests/${b.id}`} className="font-medium text-fg hover:underline">{b.name}</Link>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
                    <BacktestStatus b={b} />
                    {b.data_source === "synthetic" && <Pill tone="warning">Practice data</Pill>}
                    <span>{formatDate(b.start)} – {formatDate(b.end)}</span>
                    {contract && <span>· {FAMILY_LABEL[contract]}</span>}
                    <span>· {formatRelative(b.created_at)}</span>
                  </p>
                  {(b.status === "RUNNING" || b.status === "QUEUED") && <Progress value={b.progress} className="mt-2 h-1.5" aria-label={`Progress ${b.progress}%`} />}
                  {b.status === "FAILED" && b.error && <p className="mt-1 text-xs text-negative">{b.error}</p>}
                </div>
                {m && (
                  <dl className="flex gap-5 text-sm">
                    <div><dt className="text-xs text-fg-subtle">Net P/L</dt><dd><PnlText value={m.net_pnl} currency="USD" className="font-semibold" /></dd></div>
                    <div><dt className="text-xs text-fg-subtle">Trades</dt><dd className="num">{m.trades}</dd></div>
                    <div><dt className="text-xs text-fg-subtle">Wins</dt><dd className="num">{formatPct(m.win_rate, 0)}</dd></div>
                  </dl>
                )}
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" asChild><Link href={`/strategies/backtests/${b.id}`}>Open <ArrowRight aria-hidden /></Link></Button>
                  {b.status !== "RUNNING" && b.status !== "QUEUED" && (
                    <Button variant="ghost" size="icon-sm" aria-label={`Delete test ${b.name}`} onClick={() => { action.reset(); setDeleting(b); }}><Trash2 aria-hidden /></Button>
                  )}
                </div>
              </CardContent>
            </Card>
          </li>
        );
      })}
      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} title="Delete this test?" confirmLabel="Delete" destructive
        onConfirm={() => void remove()} busy={action.busy} error={action.error}>
        <p>The results and simulated trades are removed. Your strategy is not affected.</p>
      </ConfirmDialog>
    </ul>
  );
}
