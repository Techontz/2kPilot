"use client";

import { FlaskConical, Plus, Trash2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { EmptyState, Notice, Pnl } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiRequest } from "@/lib/api";
import { formatDate, formatPct, formatTime, humanize } from "@/lib/format";
import type { Tone } from "@/lib/status";
import type { BacktestSummary } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { BacktestReport } from "./BacktestReport";
import { NewBacktest } from "./NewBacktest";

const STATUS: Record<BacktestSummary["status"], Tone> = { QUEUED: "info", RUNNING: "info", COMPLETED: "positive", FAILED: "negative" };
const KIND: Record<string, string> = { SINGLE: "Single", SPLIT: "In/out of sample", WALK_FORWARD: "Walk-forward", SENSITIVITY: "Sensitivity" };

export function BacktestingScreen() {
  const { isOwner } = useSession();
  const list = useApiResource<BacktestSummary[]>("/backtests");
  const params = useSearchParams();
  const preset = params.get("version");
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(() => preset !== null);
  const running = list.data?.some((b) => b.status === "RUNNING" || b.status === "QUEUED");
  useLiveRefresh(["notification"], () => void list.reload());

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => void list.reload(), 2000);
    return () => window.clearInterval(timer);
  }, [running, list]);

  const current = list.data?.find((b) => b.id === selected);
  return (
    <>
      <PageHeader
        title="Backtesting"
        description="Test a strategy on history with realistic costs, using the exact strategy and risk code that trades live. Past results never guarantee future results."
        actions={isOwner && <Button variant="primary" onClick={() => setCreating(true)}><Plus aria-hidden className="size-4" />New backtest</Button>}
      />
      {current ? (
        <>
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <div>
              <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>← All backtests</Button>
              <h2 className="mt-2 text-lg font-semibold">{current.name}</h2>
              <p className="text-sm text-fg-muted">{KIND[current.kind] ?? current.kind} · {formatDate(current.start)} – {formatDate(current.end)}</p>
            </div>
            {isOwner && current.status !== "RUNNING" && current.status !== "QUEUED" && (
              <Button variant="ghost" size="sm" onClick={() => void apiRequest(`/backtests/${current.id}`, { method: "DELETE" }).then(() => { setSelected(null); void list.reload(); })}>
                <Trash2 aria-hidden className="size-4" />Delete
              </Button>
            )}
          </div>
          <BacktestReport key={`${current.id}-${current.status}`} id={current.id} />
        </>
      ) : (
        <Card>
          <CardHeader title="Runs" />
          {list.data?.length === 0 ? (
            <EmptyState icon={FlaskConical} title="No backtests yet" action={isOwner && <Button variant="primary" onClick={() => setCreating(true)}>Run your first backtest</Button>}>
              You need historical data first (Markets page). Synthetic data is fine for learning the tool, but only real data can say anything about an edge.
            </EmptyState>
          ) : (
            <DataTable rows={list.data} loading={list.loading} error={list.error?.message} rowKey={(b) => b.id} onRowClick={(b) => setSelected(b.id)} columns={[
              { key: "n", header: "Run", cell: (b) => <span><span className="font-medium">{b.name}</span><span className="block text-xs text-fg-subtle">{KIND[b.kind] ?? b.kind} · {formatTime(b.created_at)}</span></span> },
              { key: "d", header: "Data", hideBelow: "md", cell: (b) => <span className="text-xs">{b.symbol} {b.timeframe} {b.data_source === "synthetic" && <Badge tone="warning">SYNTHETIC</Badge>}</span> },
              { key: "s", header: "Status", cell: (b) => <Badge tone={STATUS[b.status]}>{b.status === "RUNNING" ? `Running ${b.progress}%` : humanize(b.status)}</Badge> },
              { key: "t", header: "Trades", align: "right", hideBelow: "sm", cell: (b) => b.summary?.trades ?? "—" },
              { key: "r", header: "Return", align: "right", cell: (b) => <Pnl value={b.summary?.return_pct}>{formatPct(b.summary?.return_pct, 2, true)}</Pnl> },
              { key: "dd", header: "Max DD", align: "right", hideBelow: "sm", cell: (b) => formatPct(b.summary?.max_drawdown_pct) },
            ]} />
          )}
        </Card>
      )}
      {list.error && <Notice tone="danger">{list.error.message}</Notice>}
      {creating && <NewBacktest open presetVersion={preset} onClose={() => setCreating(false)} onCreated={(b) => { setCreating(false); void list.reload(); setSelected(b.id); }} />}
    </>
  );
}
