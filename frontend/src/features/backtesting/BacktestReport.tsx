"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { BarChart } from "@/components/charts/BarChart";
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import { toSeries } from "@/components/charts/theme";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { KeyValue, Loading, Notice, Pnl, SideBadge } from "@/components/ui/Misc";
import { Term } from "@/components/ui/Term";
import { cn } from "@/lib/cn";
import { formatDate, formatMoney, formatNumber, formatPct, formatPnl, formatPrice, formatTime, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Backtest, BacktestTrade, Metrics } from "@/lib/types";

export function BacktestReport({ id }: { id: string }) {
  const run = useApi<Backtest>(`/backtests/${id}`, undefined, 3000);
  const b = run.data;
  const finished = b?.status === "COMPLETED";
  const trades = useApi<BacktestTrade[]>(finished && b?.kind !== "SENSITIVITY" ? `/backtests/${id}/trades` : null);
  if (!b) return run.error ? <Notice tone="danger">{run.error}</Notice> : <Loading />;
  const m = b.metrics;
  const warnings = (b.report?.warnings as string[] | undefined) ?? [];
  return (
    <div className="space-y-6">
      <Link href="/backtesting" className="inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg"><ArrowLeft className="size-4" aria-hidden /> Backtesting</Link>
      <div>
        <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold tracking-tight">{b.name}
          {b.data_source === "synthetic" && <Badge tone="warning">SYNTHETIC DATA</Badge>}
          <Badge tone={b.status === "COMPLETED" ? "positive" : b.status === "FAILED" ? "negative" : "info"}>{b.status === "RUNNING" ? `Running ${b.progress}%` : b.status.toLowerCase()}</Badge>
        </h1>
        <p className="mt-1 text-sm text-fg-muted">{b.symbol} {b.timeframe} · {formatDate(b.start)} – {formatDate(b.end)} · initial {formatMoney(b.initial_capital, "USD")} · costs: spread {b.costs?.spread_pips ?? "from data"} pips, commission {b.costs?.commission_per_lot}/lot, slippage {b.costs?.slippage_pips} pips</p>
      </div>
      {b.status === "FAILED" && <Notice tone="danger" title="Backtest failed">{b.error}</Notice>}
      {(b.status === "QUEUED" || b.status === "RUNNING") && <Notice tone="info" title="Running on the trading engine">This page updates automatically.</Notice>}
      {warnings.map((w) => <Notice key={w} tone="warning">{w}</Notice>)}
      {m && <MetricsView m={m} />}
      {b.kind === "SPLIT" && b.children && <Children rows={b.children} title="In-sample vs out-of-sample" />}
      {b.kind === "WALK_FORWARD" && b.children && <Children rows={b.children} title="Walk-forward windows (out-of-sample)" />}
      {trades.data && (
        <Card>
          <CardHeader title="Trade history" description={`${trades.data.length} simulated trades. Entry is always at the open of the bar after the signal.`} />
          <DataTable
            caption="Backtest trades"
            rows={trades.data}
            rowKey={(r) => r.id}
            columns={[
              { key: "entry", header: "Entry", cell: (r) => <span className="text-fg-muted">{formatTime(r.entry_time)}</span> },
              { key: "side", header: "Side", cell: (r) => <SideBadge side={r.side} /> },
              { key: "price", header: "Entry price", align: "right", hideBelow: "sm", cell: (r) => formatPrice(r.entry_price, b.symbol) },
              { key: "exit", header: "Exit", align: "right", hideBelow: "md", cell: (r) => formatPrice(r.exit_price, b.symbol) },
              { key: "reason", header: "Reason", hideBelow: "md", cell: (r) => <span className="text-fg-muted">{humanize(r.exit_reason)}</span> },
              { key: "r", header: "R", align: "right", cell: (r) => Number(r.r_multiple).toFixed(2) },
              { key: "pnl", header: "Net P/L", align: "right", cell: (r) => <Pnl value={r.net_pnl}>{formatPnl(r.net_pnl)}</Pnl> },
            ]}
          />
        </Card>
      )}
    </div>
  );
}

export function MetricsView({ m }: { m: Metrics }) {
  const equity = useMemo(() => toSeries(m.equity_curve ?? [], (p) => p.t, (p) => p.equity), [m.equity_curve]);
  const drawdown = useMemo(() => toSeries(m.drawdown_curve ?? [], (p) => p.t, (p) => p.dd), [m.drawdown_curve]);
  return (
    <>
      <section aria-label="Results" className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
        <Kpi label="Return" value={formatPct(m.return_pct, 2, true)} tone={m.return_pct} />
        <Kpi label="Net P/L" value={formatPnl(m.net_pnl)} tone={m.net_pnl} />
        <Kpi label="Win rate" value={formatPct(m.win_rate, 1)} />
        <Kpi label={<Term id="profitFactor" />} value={m.profit_factor === null ? "—" : formatNumber(m.profit_factor)} />
        <Kpi label={<Term id="expectancy" />} value={m.expectancy === null ? "—" : `${formatPnl(m.expectancy)} · ${formatNumber(m.expectancy_r, 2)} R`} />
        <Kpi label={<Term id="drawdown">Max drawdown</Term>} value={formatPct(m.max_drawdown_pct)} />
        <Kpi label={<Term id="riskReward">Average R:R</Term>} value={m.avg_rr === null ? "—" : `1 : ${formatNumber(m.avg_rr)}`} />
        <Kpi label="Trades" value={String(m.trades)} hint={`${m.wins} won · ${m.losses} lost`} />
        <Kpi label="Longest losing streak" value={String(m.max_consecutive_losses)} />
        <Kpi label="Total costs" value={formatMoney(m.total_costs)} />
      </section>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card><CardHeader title="Equity curve" /><CardBody>{equity.length > 1 ? <TimeSeriesChart data={equity} label="Equity" format={(v) => formatMoney(v)} /> : <p className="text-sm text-fg-muted">Not enough trades for a curve.</p>}</CardBody></Card>
        <Card><CardHeader title="Drawdown" description="Distance below the previous equity peak" /><CardBody>{drawdown.length > 1 ? <TimeSeriesChart data={drawdown} label="Drawdown" variant="drawdown" format={(v) => `${v.toFixed(2)}%`} /> : <p className="text-sm text-fg-muted">—</p>}</CardBody></Card>
      </div>
      <Card>
        <CardHeader title="Monthly results" />
        <CardBody>
          {m.monthly.length > 1 && <BarChart bars={m.monthly.map((x) => ({ label: x.month, value: x.net_pnl, detail: `${x.trades} trades` }))} format={(v) => formatPnl(v)} label="Monthly net P/L" />}
          <DataTable caption="Monthly results" rows={m.monthly} rowKey={(r) => r.month} columns={[
            { key: "m", header: "Month", cell: (r) => r.month },
            { key: "t", header: "Trades", align: "right", cell: (r) => r.trades },
            { key: "p", header: "Net P/L", align: "right", cell: (r) => <Pnl value={r.net_pnl}>{formatPnl(r.net_pnl)}</Pnl> },
            { key: "r", header: "Return", align: "right", cell: (r) => formatPct(r.return_pct, 2, true) },
          ]} />
        </CardBody>
      </Card>
    </>
  );
}

function Kpi({ label, value, hint, tone }: { label: React.ReactNode; value: string; hint?: string; tone?: number | null }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs text-fg-muted">{label}</div>
      <div className={cn("num mt-1 text-lg font-semibold", tone !== undefined && tone !== null && tone > 0 && "text-positive", tone !== undefined && tone !== null && tone < 0 && "text-negative")}>{value}</div>
      {hint && <div className="text-xs text-fg-subtle">{hint}</div>}
    </div>
  );
}

function Children({ rows, title }: { rows: Backtest[]; title: string }) {
  return (
    <Card>
      <CardHeader title={title} />
      <CardBody>
        <KeyValue items={rows.map((c) => [
          `${humanize(c.kind)} · ${formatDate(c.start)} – ${formatDate(c.end)}`,
          c.metrics ? `${formatPct(c.metrics.return_pct, 2, true)} · ${c.metrics.trades} trades · PF ${c.metrics.profit_factor ?? "—"}` : c.status.toLowerCase(),
        ])} />
      </CardBody>
    </Card>
  );
}
