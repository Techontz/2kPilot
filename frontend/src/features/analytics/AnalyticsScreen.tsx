"use client";

import { BarChart3 } from "lucide-react";
import { useMemo, useState } from "react";
import { BarChart } from "@/components/charts/BarChart";
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import { toSeries } from "@/components/charts/theme";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Segmented } from "@/components/ui/Fields";
import { EmptyState, KeyValue, Loading, Notice, Pnl } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { formatMoney, formatNumber, formatPct, formatPnl, humanize } from "@/lib/format";
import type { GroupStat, Metrics, Performance } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { MetricTiles } from "@/features/backtesting/BacktestReport";
import { AccountPicker } from "@/features/shared/AccountPicker";
import { useAccounts } from "@/features/shared/useAccounts";

type Period = "7" | "30" | "90" | "all";
type Bucket = "daily" | "weekly" | "monthly";

function Group({ title, rows }: { title: string; rows: GroupStat[] | undefined }) {
  return (
    <Card>
      <CardHeader title={title} />
      <DataTable rows={rows ?? []} rowKey={(r) => r.key} empty="No closed trades." columns={[
        { key: "k", header: "", cell: (r) => humanize(r.key) },
        { key: "t", header: "Trades", align: "right", cell: (r) => r.trades },
        { key: "w", header: "Win rate", align: "right", hideBelow: "sm", cell: (r) => formatPct(r.win_rate, 1) },
        { key: "pf", header: "PF", align: "right", hideBelow: "sm", cell: (r) => (r.profit_factor == null ? "—" : formatNumber(r.profit_factor)) },
        { key: "n", header: "Net", align: "right", cell: (r) => <Pnl value={r.net_pnl}>{formatPnl(r.net_pnl)}</Pnl> },
      ]} />
    </Card>
  );
}

export function AnalyticsScreen() {
  const acc = useAccounts({ allowAll: true });
  const [period, setPeriod] = useState<Period>("30");
  const [bucket, setBucket] = useState<Bucket>("daily");
  const params = new URLSearchParams();
  if (acc.selected) params.set("account_id", acc.selected);
  if (period !== "all") params.set("days", period);
  const perf = useApiResource<Performance>(`/analytics/performance?${params.toString()}`);
  useLiveRefresh(["journal"], () => void perf.reload(), 2000);
  const p = perf.data;
  const equity = useMemo(() => toSeries(p?.balance_history ?? [], (x) => x.t, (x) => x.equity), [p?.balance_history]);
  const balance = useMemo(() => toSeries(p?.balance_history ?? [], (x) => x.t, (x) => x.balance), [p?.balance_history]);
  const dd = useMemo(() => toSeries(p?.drawdown_curve ?? [], (x) => x.t, (x) => x.dd), [p?.drawdown_curve]);
  const [curve, setCurve] = useState<"equity" | "balance" | "drawdown">("equity");
  const bars = bucket === "monthly"
    ? (p?.monthly ?? []).map((m) => ({ label: m.month, value: m.net_pnl ?? 0, detail: `${m.trades} trades` }))
    : (p?.[bucket] ?? []).map((d) => ({ label: d.period, value: d.net_pnl, detail: `${d.trades} trades` }));
  const fmtMoney = useMemo(() => (v: number) => formatMoney(v), []);
  const fmtPct = useMemo(() => (v: number) => formatPct(v), []);
  const ex = p?.execution;

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Performance measured from the robot's own stored records. Nothing here is estimated or sample data."
        actions={
          <div className="flex flex-wrap gap-2">
            {acc.accounts.length > 1 && <AccountPicker accounts={acc.accounts} value={acc.selected} onChange={acc.setSelected} allowAll />}
            <Segmented label="Period" value={period} onChange={setPeriod} options={[{ value: "7", label: "7d" }, { value: "30", label: "30d" }, { value: "90", label: "90d" }, { value: "all", label: "All" }]} />
          </div>
        }
      />
      {!p && !perf.error && <Loading />}
      {perf.error && <Notice tone="danger">{perf.error.message}</Notice>}
      {p && !p.has_data && (
        <Card>
          <EmptyState icon={BarChart3} title="No trading records yet">
            Analytics fill in automatically once an account is connected and the robot starts recording snapshots and trades. For research on
            history, use Backtesting.
          </EmptyState>
        </Card>
      )}
      {p && p.has_data && (
        <div className="space-y-6">
          {p.simulated && <Notice tone="info" title="PAPER / SIMULATION">These results come from simulated trading. They show that the pipeline works — not that the strategy has an edge.</Notice>}
          <MetricTiles m={p as Metrics} />
          <div className="grid gap-6 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader title={curve === "drawdown" ? "Drawdown" : curve === "equity" ? "Equity" : "Balance"}
                description={curve === "equity" ? "Includes open P/L" : curve === "balance" ? "Closed trades only" : "Fall from the running peak"}
                action={<Segmented size="sm" label="Curve" value={curve} onChange={setCurve} options={[{ value: "equity", label: "Equity" }, { value: "balance", label: "Balance" }, { value: "drawdown", label: "Drawdown" }]} />} />
              <CardBody>
                {(curve === "drawdown" ? dd : curve === "equity" ? equity : balance).length > 1 ? (
                  curve === "drawdown"
                    ? <TimeSeriesChart data={dd} label="Drawdown" variant="drawdown" format={fmtPct} />
                    : <TimeSeriesChart data={curve === "equity" ? equity : balance} label={curve} format={fmtMoney} variant={curve === "balance" ? "line" : "area"} />
                ) : <p className="py-12 text-center text-sm text-fg-subtle">Not enough snapshots in this period yet.</p>}
              </CardBody>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader title="Results by period" action={<Segmented size="sm" label="Bucket" value={bucket} onChange={setBucket} options={[{ value: "daily", label: "Day" }, { value: "weekly", label: "Week" }, { value: "monthly", label: "Month" }]} />} />
              <CardBody>
                {bars.length ? <BarChart bars={bars.slice(-40)} label={`${bucket} net P/L`} format={(v) => formatPnl(v)} /> : <p className="py-12 text-center text-sm text-fg-subtle">No closed trades in this period.</p>}
              </CardBody>
            </Card>
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <Group title="By strategy" rows={p.by_strategy} />
            <Group title="By instrument" rows={p.by_symbol} />
            <Group title="By session" rows={p.by_session} />
          </div>
          {ex && (
            <Card>
              <CardHeader title="Execution quality" description="How well orders are filled — slippage and failures cost money the backtest may not show." />
              <CardBody className="grid gap-6 md:grid-cols-2">
                <KeyValue items={[
                  ["Entry orders", ex.orders],
                  ["Fill rate", formatPct(ex.fill_rate, 1)],
                  ["Avg / worst slippage", `${ex.avg_slippage_pips ?? "—"} / ${ex.worst_slippage_pips ?? "—"} pips`],
                  ["Avg time to fill", ex.avg_fill_seconds !== null ? `${ex.avg_fill_seconds}s` : "—"],
                  ["Unresolved orders", <span key="u" className={ex.unresolved_orders ? "text-warning" : undefined}>{ex.unresolved_orders}</span>],
                  ["Unrealised P/L now", <Pnl key="o" value={p.unrealized_pnl}>{formatPnl(p.unrealized_pnl)}</Pnl>],
                ]} />
                <div>
                  <p className="mb-2 text-xs font-medium tracking-wide text-fg-subtle uppercase">Most common rejection reasons</p>
                  {ex.top_rejections.length === 0 ? <p className="text-sm text-fg-subtle">None.</p> : (
                    <KeyValue items={ex.top_rejections.map((r) => [<span key={r.reason} className="text-xs">{r.reason.replace("Trade rejected: ", "")}</span>, r.count])} />
                  )}
                </div>
              </CardBody>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
