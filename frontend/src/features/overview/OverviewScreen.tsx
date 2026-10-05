"use client";

import { AlertTriangle, ArrowRight, Cable, CircleCheck, LineChart, Rocket } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConnectionBadge, EmptyState, EnvBadge, Loading, Notice } from "@/components/ui/Misc";
import { Term } from "@/components/ui/Term";
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import { toSeries } from "@/components/charts/theme";
import { cn } from "@/lib/cn";
import { formatMoney, formatPct, formatPnl, formatRelative, pnlTone } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { deriveRobotStatus } from "@/lib/status";
import type { Overview } from "@/lib/types";
import { PositionsMini, RecentTradesMini } from "../shared/tables";

export function OverviewScreen() {
  const { account, accounts } = useAppData();
  const overview = useApi<Overview>(account ? "/overview" : null, { account_id: account?.id }, 5000);

  if (accounts && accounts.length === 0) return <Welcome />;
  if (!account || (!overview.data && overview.loading)) return <Loading label="Loading your dashboard…" />;
  if (overview.error && !overview.data) return <Notice tone="danger" title="Could not load the overview">{overview.error}</Notice>;
  const data = overview.data;
  if (!data?.account || !data.figures) return <Loading />;
  return <Dashboard data={data} />;
}

function Dashboard({ data }: { data: Overview }) {
  const a = data.account!;
  const f = data.figures!;
  const robot = deriveRobotStatus(data.robot);
  const curve = useMemo(() => toSeries(data.equity_curve ?? [], (p) => p.t, (p) => p.equity), [data.equity_curve]);
  const ccy = a.currency;
  const money = (v: number) => formatMoney(v, ccy);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{a.label}</h1>
            <EnvBadge env={a.environment} />
            <ConnectionBadge status={a.connection_status} />
          </div>
          <p className="mt-1 text-sm text-fg-muted">
            {a.broker} · risk profile {a.risk_profile ?? <span className="text-warning">not assigned</span>} · synced {formatRelative(a.synced_at)}
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/trade"><Button>New trade</Button></Link>
          <Link href="/brokers"><Button variant="ghost">Manage account</Button></Link>
        </div>
      </div>

      <section aria-label="Key figures" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        <Figure label={<Term id="balance" />} value={f.balance !== null ? money(f.balance) : "—"} />
        <Figure label={<Term id="equity" />} value={f.equity !== null ? money(f.equity) : "—"} />
        <Figure label="Today's P/L" value={formatPnl(f.today_pnl, ccy)} tone={pnlTone(f.today_pnl)} hint="Closed today" />
        <Figure label="Total P/L" value={formatPnl(f.total_pnl, ccy)} tone={pnlTone(f.total_pnl)} hint="All closed trades" />
        <Figure label="Open P/L" value={formatPnl(f.open_pnl, ccy)} tone={pnlTone(f.open_pnl)} hint="Unrealised, still moving" />
        <Figure label="Open positions" value={String(f.open_positions)} />
        <Figure label={<Term id="drawdown">Current drawdown</Term>} value={formatPct(f.drawdown_pct)} hint={f.max_drawdown_pct ? `Limit ${formatPct(f.max_drawdown_pct, 1)}` : "No limit set"} meter={limitRatio(f.drawdown_pct, f.max_drawdown_pct)} />
        <Figure label={<Term id="openRisk">Risk used</Term>} value={formatPct(f.risk_used_pct)} hint={f.max_total_risk_pct ? `of ${formatPct(f.max_total_risk_pct, 1)} allowed` : "If every stop is hit"} meter={limitRatio(f.risk_used_pct, f.max_total_risk_pct)} />
        <Figure label="Active strategies" value={String(f.active_strategies)} hint={f.active_strategies ? "Enabled on this account" : "None enabled"} />
        <Figure label="Broker connection" value={<span className="text-base">{humanStatus(a.connection_status)}</span>} hint={a.connection_detail ?? undefined} tone={a.connection_status === "CONNECTED" ? "positive" : a.connection_status === "ERROR" ? "negative" : "neutral"} />
        <Figure label="Robot" value={<span className="text-base">{robot.label}</span>} hint={robot.detail} tone={robot.tone === "positive" ? "positive" : robot.tone === "negative" ? "negative" : "neutral"} className="col-span-2 md:col-span-1 xl:col-span-2" />
      </section>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Equity" description={a.environment === "PAPER" ? "Simulated account — PAPER" : "From broker balance snapshots"} />
          <CardBody>
            {curve.length > 1 ? (
              <TimeSeriesChart data={curve} label="Equity curve" format={(v) => formatMoney(v)} height={260} />
            ) : (
              <EmptyState icon={LineChart} title="No equity history yet">
                The curve starts as soon as the engine records balance snapshots for this account (every 15 minutes while connected).
              </EmptyState>
            )}
          </CardBody>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader title="Risk alerts" />
            <CardBody className="space-y-2">
              {data.alerts && data.alerts.length > 0 ? (
                data.alerts.map((alert, i) => (
                  <div key={i} className={cn("flex gap-2.5 rounded-lg border px-3 py-2 text-sm", alert.severity === "critical" ? "border-negative/30 bg-negative-soft text-negative" : "border-warning/30 bg-warning-soft text-warning")}>
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                    <span className="text-fg-muted">{alert.message}</span>
                  </div>
                ))
              ) : (
                <p className="flex items-center gap-2 text-sm text-fg-muted"><CircleCheck className="size-4 text-positive" aria-hidden /> No risk alerts.</p>
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Strategies" action={<Link href="/strategies" className="text-xs text-accent hover:underline">Manage</Link>} />
            <CardBody className="space-y-3">
              {data.strategies && data.strategies.length > 0 ? data.strategies.map((s) => (
                <div key={s.id} className="flex items-start justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <p className="truncate text-fg">{s.strategy} <span className="text-fg-subtle">v{s.version}</span> · {s.symbol}</p>
                    <p className="truncate text-xs text-fg-subtle">{s.status_reason ?? (s.last_bar_evaluated ? `Last bar checked ${formatRelative(s.last_bar_evaluated)}` : "Waiting for the next closed bar")}</p>
                  </div>
                  <Badge tone={s.status === "ENABLED" ? "positive" : "neutral"} dot>{s.status === "ENABLED" ? "Enabled" : "Paused"}</Badge>
                </div>
              )) : <p className="text-sm text-fg-muted">No strategy assigned to this account.</p>}
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title="Active positions" action={<Link href="/positions" className="text-xs text-accent hover:underline">All positions</Link>} />
          <PositionsMini rows={data.positions ?? []} currency={ccy} />
        </Card>
        <Card>
          <CardHeader title="Recent trades" action={<Link href="/history" className="text-xs text-accent hover:underline">History</Link>} />
          <RecentTradesMini rows={data.recent_trades ?? []} currency={ccy} />
        </Card>
      </div>
    </div>
  );
}

function limitRatio(used: number | null, limit: number | null): number | null {
  return used !== null && limit ? Math.min(1, used / limit) : null;
}

function humanStatus(status: string): string {
  return { CONNECTED: "Connected", DISCONNECTED: "Disconnected", RECONNECTING: "Reconnecting", ERROR: "Error" }[status] ?? status;
}

function Figure({ label, value, hint, tone = "neutral", meter, className }: {
  label: React.ReactNode; value: React.ReactNode; hint?: string; tone?: "positive" | "negative" | "neutral"; meter?: number | null; className?: string;
}) {
  return (
    <div className={cn("min-w-0 rounded-xl border border-line bg-surface px-4 py-3.5", className)}>
      <div className="text-xs font-medium text-fg-muted">{label}</div>
      <div className={cn("num mt-1.5 text-base font-semibold break-words sm:text-lg", tone === "positive" ? "text-positive" : tone === "negative" ? "text-negative" : "text-fg")}>{value}</div>
      {meter !== undefined && meter !== null && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-raised" aria-hidden>
          <div className={cn("h-full rounded-full", meter >= 0.9 ? "bg-negative" : meter >= 0.7 ? "bg-warning" : "bg-positive")} style={{ width: `${meter * 100}%` }} />
        </div>
      )}
      {hint && <div className="mt-1 truncate text-xs text-fg-subtle" title={hint}>{hint}</div>}
    </div>
  );
}

function Welcome() {
  const steps = [
    { title: "Add a Paper account", text: "Brokers → Add Broker → Paper Trading. No real money, simulated prices.", href: "/brokers/new" },
    { title: "Turn trading on for it", text: "On the account card, keep the default risk profile and switch “Trading enabled” on.", href: "/brokers" },
    { title: "Assign Trend Pullback V1", text: "Strategies → Assign → choose the paper account and EURUSD → Enable.", href: "/strategies" },
    { title: "Resume trading", text: "Press “Resume trading” in the top bar. STOP TRADING is always one click away.", href: "/risk" },
  ];
  return (
    <div className="mx-auto max-w-3xl space-y-6 py-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight"><Rocket className="size-6 text-accent" aria-hidden /> Welcome to 2kFX</h1>
        <p className="mt-2 text-fg-muted">Learn and test safely first. Start with a Paper account — everything is simulated and clearly labelled PAPER. Connect a Deriv or MetaTrader 5 demo account when you are ready.</p>
      </div>
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.title}>
            <Link href={s.href} className="flex items-center gap-4 rounded-xl border border-line bg-surface px-4 py-3.5 hover:border-line-strong">
              <span className="num flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-raised text-sm text-fg">{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-fg">{s.title}</span>
                <span className="block text-sm text-fg-muted">{s.text}</span>
              </span>
              <ArrowRight className="size-4 text-fg-subtle" aria-hidden />
            </Link>
          </li>
        ))}
      </ol>
      <Link href="/brokers/new"><Button variant="primary"><Cable className="size-4" aria-hidden /> Connect your first account</Button></Link>
    </div>
  );
}
