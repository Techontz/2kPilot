"use client";

import { useMemo, useState } from "react";
import { BarChart } from "@/components/charts/BarChart";
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import { toSeries } from "@/components/charts/theme";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Segmented } from "@/components/ui/Fields";
import { KeyValue, Loading, Notice, Pnl, SideBadge } from "@/components/ui/Misc";
import { StatCard } from "@/components/ui/StatCard";
import { Term } from "@/components/ui/Term";
import { formatDate, formatMoney, formatNumber, formatPct, formatPnl, formatPrice, formatTime, humanize } from "@/lib/format";
import type { BacktestDetail, BacktestTradeRow, GroupStat, Metrics } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

export function MetricTiles({ m }: { m: Metrics }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <StatCard label="Net P/L" value={<Pnl value={m.net_pnl}>{formatPnl(m.net_pnl)}</Pnl>} hint={`${formatPct(m.return_pct, 2, true)} return`} />
      <StatCard label="Trades" value={m.trades} hint={`${m.wins} wins · ${m.losses} losses`} />
      <StatCard label="Win rate" value={formatPct(m.win_rate, 1)} hint={`Avg win ${formatMoney(m.avg_win)} · loss ${formatMoney(m.avg_loss)}`} />
      <StatCard label={<Term id="profitFactor" />} value={m.profit_factor === null ? "—" : formatNumber(m.profit_factor)} hint={m.profit_factor === null && m.trades ? "No losing trades" : "Above 1 = more won than lost"} />
      <StatCard label={<Term id="expectancy" />} value={<Pnl value={m.expectancy}>{formatPnl(m.expectancy)}</Pnl>} hint={m.expectancy_r !== null ? `${formatNumber(m.expectancy_r, 3)} R per trade` : undefined} />
      <StatCard label={<Term id="drawdown">Max drawdown</Term>} value={formatPct(m.max_drawdown_pct)} hint={formatMoney(m.max_drawdown)} />
      <StatCard label={<Term id="riskReward">Avg R:R</Term>} value={m.avg_rr === null ? "—" : `1 : ${formatNumber(m.avg_rr)}`} hint="Average win ÷ average loss" />
      <StatCard label="Streaks" value={`${m.max_consecutive_wins} / ${m.max_consecutive_losses}`} hint="Longest win / loss run" />
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: GroupStat[] }) {
  return (
    <Card>
      <CardHeader title={title} />
      <DataTable rows={rows} rowKey={(r) => r.key} empty="No trades." columns={[
        { key: "k", header: "", cell: (r) => humanize(r.key) },
        { key: "t", header: "Trades", align: "right", cell: (r) => r.trades },
        { key: "w", header: "Win rate", align: "right", cell: (r) => formatPct(r.win_rate, 1) },
        { key: "pf", header: "PF", align: "right", hideBelow: "sm", cell: (r) => (r.profit_factor === null ? "—" : formatNumber(r.profit_factor)) },
        { key: "p", header: "Net", align: "right", cell: (r) => <Pnl value={r.net_pnl}>{formatPnl(r.net_pnl)}</Pnl> },
      ]} />
    </Card>
  );
}

export function PerformanceCharts({ m, currency = "USD" }: { m: Metrics; currency?: string }) {
  const [view, setView] = useState<"equity" | "drawdown">("equity");
  const equity = useMemo(() => toSeries(m.equity_curve, (p) => p.t, (p) => p.equity), [m.equity_curve]);
  const dd = useMemo(() => toSeries(m.drawdown_curve, (p) => p.t, (p) => p.dd), [m.drawdown_curve]);
  const fmtMoney = useMemo(() => (v: number) => `${formatMoney(v)} ${currency}`, [currency]);
  const fmtPct = useMemo(() => (v: number) => formatPct(v), []);
  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <Card className="lg:col-span-3">
        <CardHeader title={view === "equity" ? "Equity curve" : "Drawdown"} action={<Segmented size="sm" label="Chart" value={view} onChange={setView} options={[{ value: "equity", label: "Equity" }, { value: "drawdown", label: "Drawdown" }]} />} />
        <CardBody>
          {view === "equity" ? (
            equity.length > 1 ? <TimeSeriesChart data={equity} label="Equity curve" format={fmtMoney} /> : <p className="py-10 text-center text-sm text-fg-subtle">Not enough points.</p>
          ) : dd.length > 1 ? <TimeSeriesChart data={dd} label="Drawdown from peak" variant="drawdown" format={fmtPct} /> : <p className="py-10 text-center text-sm text-fg-subtle">No drawdown data.</p>}
        </CardBody>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title="Monthly results" description="Net P/L per month" />
        <CardBody>
          {m.monthly.length ? (
            <BarChart label="Monthly net P/L" bars={m.monthly.map((x) => ({ label: x.month, value: x.net_pnl ?? 0, detail: `${x.trades} trades · ${formatPct(x.return_pct, 2, true)}` }))} format={(v) => formatPnl(v)} />
          ) : <p className="py-10 text-center text-sm text-fg-subtle">No closed trades.</p>}
        </CardBody>
      </Card>
    </div>
  );
}

const PAGE = 25;

function TradesTable({ id }: { id: string }) {
  const trades = useApiResource<BacktestTradeRow[]>(`/backtests/${id}/trades`, { refetchOnFocus: false });
  const [shown, setShown] = useState(PAGE);
  const total = trades.data?.length ?? 0;
  return (
    <Card>
      <CardHeader title={`Trades (${total})`} description="Simulated — entries at the next bar's open, costs included." />
      <DataTable rows={trades.data ? trades.data.slice(0, shown) : null} loading={trades.loading} rowKey={(t) => t.id} empty="No trades in this run." columns={[
        { key: "e", header: "Entry", cell: (t) => <span className="text-xs text-fg-muted">{formatTime(t.entry_time)}</span> },
        { key: "s", header: "Side", cell: (t) => <SideBadge side={t.side} /> },
        { key: "v", header: "Lots", align: "right", hideBelow: "sm", cell: (t) => t.volume },
        { key: "p", header: "Entry → exit", align: "right", hideBelow: "md", cell: (t) => `${formatPrice(t.entry_price)} → ${formatPrice(t.exit_price)}` },
        { key: "x", header: "Exit", hideBelow: "sm", cell: (t) => <span className="text-xs">{humanize(t.exit_reason)}</span> },
        { key: "c", header: "Costs", align: "right", hideBelow: "lg", cell: (t) => formatMoney(t.costs) },
        { key: "r", header: "R", align: "right", cell: (t) => t.r_multiple },
        { key: "n", header: "Net", align: "right", cell: (t) => <Pnl value={t.net_pnl}>{formatPnl(t.net_pnl)}</Pnl> },
      ]} />
      {total > shown && (
        <div className="border-t border-line px-5 py-3 text-center">
          <Button size="sm" onClick={() => setShown((n) => n + PAGE * 4)}>Show more ({total - shown} remaining)</Button>
        </div>
      )}
    </Card>
  );
}

function SplitReport({ report }: { report: Record<string, unknown> }) {
  const is = report.in_sample as Partial<Metrics>;
  const oos = report.out_of_sample as Partial<Metrics>;
  const rows: [string, (m: Partial<Metrics>) => string][] = [
    ["Trades", (m) => String(m.trades ?? "—")], ["Return", (m) => formatPct(m.return_pct, 2, true)],
    ["Win rate", (m) => formatPct(m.win_rate, 1)], ["Profit factor", (m) => (m.profit_factor == null ? "—" : formatNumber(m.profit_factor))],
    ["Expectancy (R)", (m) => (m.expectancy_r == null ? "—" : formatNumber(m.expectancy_r, 3))], ["Max drawdown", (m) => formatPct(m.max_drawdown_pct)],
  ];
  return (
    <Card>
      <CardHeader title="In-sample vs out-of-sample" description={`Split at ${formatDate(report.split_at as string)}. The out-of-sample period was never used to choose anything.`} />
      <DataTable rows={rows} rowKey={(r) => r[0]} columns={[
        { key: "m", header: "Metric", cell: (r) => r[0] },
        { key: "i", header: "In-sample", align: "right", cell: (r) => r[1](is) },
        { key: "o", header: "Out-of-sample", align: "right", cell: (r) => <span className="font-semibold">{r[1](oos)}</span> },
      ]} />
    </Card>
  );
}

function WalkForwardReport({ report }: { report: Record<string, unknown> }) {
  const windows = (report.windows as { window: number; test_start: string; test_end: string; chosen: Record<string, unknown>; test: Partial<Metrics> }[]) ?? [];
  return (
    <Card>
      <CardHeader title="Walk-forward windows" description={`${report.profitable_windows} of ${report.total_windows} out-of-sample windows were profitable. The headline metrics above are the stitched out-of-sample results.`} />
      <DataTable rows={windows} rowKey={(w) => w.window} columns={[
        { key: "w", header: "#", cell: (w) => w.window },
        { key: "p", header: "Test period", cell: (w) => `${formatDate(w.test_start)} – ${formatDate(w.test_end)}` },
        { key: "c", header: "Chosen", hideBelow: "sm", cell: (w) => <span className="num text-xs">{Object.entries(w.chosen).map(([k, v]) => `${k}=${v}`).join(", ") || "defaults"}</span> },
        { key: "t", header: "Trades", align: "right", cell: (w) => w.test.trades ?? 0 },
        { key: "r", header: "Return", align: "right", cell: (w) => <Pnl value={w.test.return_pct}>{formatPct(w.test.return_pct, 2, true)}</Pnl> },
      ]} />
    </Card>
  );
}

function SensitivityReport({ report }: { report: Record<string, unknown> }) {
  const results = (report.results as ({ params: Record<string, unknown> } & Partial<Metrics>)[]) ?? [];
  return (
    <Card>
      <CardHeader title="Parameter sensitivity" description={`${Math.round(Number(report.profitable_share ?? 0) * 100)}% of combinations were profitable; returns spread ${formatNumber(report.return_spread as number, 1)} points.`} />
      <DataTable rows={results} rowKey={(r) => JSON.stringify(r.params)} columns={[
        { key: "p", header: "Parameters", cell: (r) => <span className="num text-xs">{Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(", ")}</span> },
        { key: "t", header: "Trades", align: "right", cell: (r) => r.trades ?? 0 },
        { key: "w", header: "Win rate", align: "right", hideBelow: "sm", cell: (r) => formatPct(r.win_rate, 1) },
        { key: "pf", header: "PF", align: "right", hideBelow: "sm", cell: (r) => (r.profit_factor == null ? "—" : formatNumber(r.profit_factor)) },
        { key: "dd", header: "Max DD", align: "right", hideBelow: "md", cell: (r) => formatPct(r.max_drawdown_pct) },
        { key: "r", header: "Return", align: "right", cell: (r) => <Pnl value={r.return_pct}>{formatPct(r.return_pct, 2, true)}</Pnl> },
      ]} />
    </Card>
  );
}

export function BacktestReport({ id }: { id: string }) {
  const { data, error } = useApiResource<BacktestDetail>(`/backtests/${id}`, { refetchOnFocus: false });
  if (error) return <Notice tone="danger">{error.message}</Notice>;
  if (!data) return <Loading />;
  if (data.status === "FAILED") return <Notice tone="danger" title="Backtest failed">{data.error}</Notice>;
  if (data.status !== "COMPLETED") return <Loading label={`Running… ${data.progress}%`} />;
  const m = data.metrics;
  const report = data.report ?? {};
  const rejections = m?.rejections ?? {};
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        {data.warnings.map((w) => <Notice key={w} tone={w.startsWith("SYNTHETIC") ? "danger" : "warning"}>{w}</Notice>)}
      </div>
      {m && <MetricTiles m={m} />}
      {m && <PerformanceCharts m={m} />}
      {data.kind === "SPLIT" && <SplitReport report={report} />}
      {data.kind === "WALK_FORWARD" && <WalkForwardReport report={report} />}
      {data.kind === "SENSITIVITY" && <SensitivityReport report={report} />}
      {m && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Breakdown title="By session" rows={m.by_session} />
          <Breakdown title="By direction" rows={m.by_side} />
          <Card>
            <CardHeader title="Why signals were not traded" description={`${m.signals ?? 0} signals from ${m.evaluations ?? 0} evaluated bars`} />
            <CardBody>
              {Object.keys(rejections).length === 0 ? <p className="text-sm text-fg-subtle">No signals were rejected.</p> : (
                <KeyValue items={Object.entries(rejections).map(([k, v]) => [k, <span key={k} className="num">{v}</span>])} />
              )}
            </CardBody>
          </Card>
        </div>
      )}
      <Card>
        <CardHeader title="Run details" description="Everything needed to reproduce this result." />
        <CardBody className="grid gap-6 md:grid-cols-2">
          <KeyValue items={[
            ["Strategy", `${data.strategy_key} (code ${data.code_version})`],
            ["Data", <span key="d">{data.symbol} {data.timeframe} <Badge tone={data.data_source === "synthetic" ? "warning" : "neutral"}>{data.data_source.toUpperCase()}</Badge></span>],
            ["Period", `${formatDate(data.start)} – ${formatDate(data.end)}`],
            ["Capital", formatMoney(data.initial_capital, "USD")],
            ["Costs", `spread ${data.costs.spread_pips ?? "from data"} · commission ${data.costs.commission_per_lot}/lot/side · slippage ${data.costs.slippage_pips} pips`],
            ["Data checksum", <span key="c" className="num text-xs">{data.data_checksum.slice(0, 16)}…</span>],
          ]} />
          <details className="text-sm">
            <summary className="cursor-pointer text-fg-muted hover:text-fg">Strategy parameters ({Object.keys(data.parameters).length})</summary>
            <div className="mt-3"><KeyValue items={Object.entries(data.parameters).map(([k, v]) => [k.replaceAll("_", " "), <span key={k} className="num">{String(v)}</span>])} /></div>
          </details>
        </CardBody>
      </Card>
      {data.kind !== "SENSITIVITY" && data.kind !== "WALK_FORWARD" && data.kind !== "SPLIT" && <TradesTable id={data.id} />}
      {data.kind === "SPLIT" && data.children?.find((c) => c.kind === "OUT_OF_SAMPLE") && <TradesTable id={data.children.find((c) => c.kind === "OUT_OF_SAMPLE")!.id} />}
    </div>
  );
}
