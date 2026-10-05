"use client";

import { BarChart3 } from "lucide-react";
import { useMemo, useState } from "react";
import { BarChart } from "@/components/charts/BarChart";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Segmented, Select } from "@/components/ui/Fields";
import { EmptyState, EnvBadge, KeyValue, Loading, Notice, Pnl } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { formatNumber, formatPct, formatPnl } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { GroupStat, Metrics, Performance } from "@/lib/types";
import { MetricsView } from "../backtesting/BacktestReport";

type Period = "7d" | "30d" | "90d" | "365d" | "all";

/** Performance from stored trades only. PAPER and real results are never mixed. */
export function AnalyticsScreen() {
  const { account, accounts } = useAppData();
  const [scope, setScope] = useState<string>("account");
  const [period, setPeriod] = useState<Period>("all");
  const [grain, setGrain] = useState<"daily" | "weekly">("daily");
  const query = scope === "account" ? { account_id: account?.id, period } : { environment: scope, period };
  const perf = useApi<Performance>(scope !== "account" || account ? "/analytics/performance" : null, query, 30000);
  const environments = useMemo(() => Array.from(new Set((accounts ?? []).map((a) => a.environment))), [accounts]);
  const p = perf.data;
  const series = (grain === "daily" ? p?.daily : p?.weekly) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="Analytics" description="Calculated only from closed trades and broker balance snapshots. Simulated (PAPER) results are kept separate from broker accounts."
        actions={<>
          <Select aria-label="Scope" className="w-56" value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="account">This account{account ? ` — ${account.label}` : ""}</option>
            {environments.map((env) => <option key={env} value={env}>All {env} accounts</option>)}
          </Select>
          <Segmented size="sm" label="Period" value={period} onChange={setPeriod} options={[{ value: "7d", label: "7D" }, { value: "30d", label: "30D" }, { value: "90d", label: "90D" }, { value: "365d", label: "1Y" }, { value: "all", label: "All" }]} />
        </>} />
      {!p ? (perf.error ? <Notice tone="danger">{perf.error}</Notice> : <Loading />) : !p.has_data ? (
        <Card><EmptyState icon={BarChart3} title="No results yet">Analytics appear after the first closed trades and balance snapshots for {p.scope.label ?? "this scope"}.</EmptyState></Card>
      ) : (
        <>
          <div className="flex items-center gap-2 text-sm text-fg-muted">{p.scope.environment && <EnvBadge env={p.scope.environment} />} {p.scope.label}{p.simulated && " · simulated results"}</div>
          <MetricsView m={p as Metrics} />
          <div className="grid gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader title={grain === "daily" ? "Daily P/L" : "Weekly P/L"} action={<Segmented size="sm" label="Grain" value={grain} onChange={setGrain} options={[{ value: "daily", label: "Daily" }, { value: "weekly", label: "Weekly" }]} />} />
              <CardBody>{series.length ? <BarChart bars={series.slice(-60).map((d) => ({ label: d.period, value: d.net_pnl, detail: `${d.trades} trades` }))} format={(v) => formatPnl(v)} label="Net P/L per period" /> : <p className="text-sm text-fg-muted">No closed trades in this period.</p>}</CardBody>
            </Card>
            <Card>
              <CardHeader title="Execution quality" description="How orders were filled — and why signals were rejected" />
              <CardBody className="space-y-4">
                <KeyValue items={[
                  ["Orders", String(p.execution?.orders ?? 0)],
                  ["Fill rate", formatPct(p.execution?.fill_rate, 1)],
                  ["Average slippage", p.execution?.avg_slippage_pips === null || p.execution?.avg_slippage_pips === undefined ? "—" : `${formatNumber(p.execution.avg_slippage_pips)} pips`],
                  ["Worst slippage", p.execution?.worst_slippage_pips === null || p.execution?.worst_slippage_pips === undefined ? "—" : `${formatNumber(p.execution.worst_slippage_pips)} pips`],
                  ["Average fill time", p.execution?.avg_fill_seconds === null || p.execution?.avg_fill_seconds === undefined ? "—" : `${formatNumber(p.execution.avg_fill_seconds)} s`],
                  ["Unresolved orders", String(p.execution?.unresolved_orders ?? 0)],
                ]} />
                {p.execution?.top_rejections.length ? (
                  <div>
                    <p className="mb-2 text-xs font-medium text-fg-subtle">Most common rejection reasons</p>
                    <ul className="space-y-1 text-sm">{p.execution.top_rejections.map((r) => <li key={r.reason} className="flex justify-between gap-3"><span className="truncate text-fg-muted">{r.reason}</span><span className="num text-fg">{r.count}</span></li>)}</ul>
                  </div>
                ) : null}
              </CardBody>
            </Card>
          </div>
          <div className="grid gap-6 xl:grid-cols-3">
            <Breakdown title="By symbol" rows={p.by_symbol ?? []} />
            <Breakdown title="By strategy" rows={p.by_strategy ?? []} />
            <Breakdown title="By session" rows={p.by_session ?? []} />
          </div>
        </>
      )}
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: GroupStat[] }) {
  return (
    <Card>
      <CardHeader title={title} />
      <DataTable caption={title} rows={rows} rowKey={(r) => r.key} columns={[
        { key: "k", header: "", cell: (r) => <span className="font-medium">{r.key}</span> },
        { key: "t", header: "Trades", align: "right", cell: (r) => r.trades },
        { key: "w", header: "Win %", align: "right", cell: (r) => formatPct(r.win_rate, 0) },
        { key: "pf", header: "PF", align: "right", cell: (r) => (r.profit_factor === null ? "—" : formatNumber(r.profit_factor)) },
        { key: "p", header: "Net", align: "right", cell: (r) => <Pnl value={r.net_pnl}>{formatPnl(r.net_pnl)}</Pnl> },
      ]} />
    </Card>
  );
}
