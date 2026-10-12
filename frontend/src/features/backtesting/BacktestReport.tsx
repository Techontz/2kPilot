"use client";

import { ArrowLeft, FlaskConical, Loader2 } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useMemo, useState } from "react";
import { Artwork } from "@/components/app/artwork";
import { Pill } from "@/components/app/badges";
import { Money, PnlText } from "@/components/app/money";
import { ErrorState, ListSkeleton, Notice } from "@/components/app/states";
import { Term } from "@/components/app/term";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { PnlBars } from "@/components/charts/PnlBars";
import { toSeries } from "@/components/charts/series";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BacktestStatus } from "@/features/strategies/BacktestsList";
import { contractSummary } from "@/lib/contracts";
import { formatCurrency, formatDate, formatDuration, formatNumber, formatPct, formatPrice, formatSignedCurrency, formatTime, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Backtest, BacktestTrade, GroupStat, Metrics, ValidationGate } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE = 50;

/** The result of one "Test on history": progress while it runs, then the honest numbers. */
export function BacktestReport({ id }: { id: string }) {
  const run = useApi<Backtest>(`/backtests/${id}`, undefined, 2500);
  const b = run.data;
  const finished = b?.status === "COMPLETED";
  const trades = useApi<BacktestTrade[]>(finished && b?.kind !== "SENSITIVITY" ? `/backtests/${id}/trades` : null);
  if (!b) return run.error ? <ErrorState message={run.error} onRetry={() => void run.reload()} /> : <ListSkeleton rows={5} />;
  const m = b.metrics;
  const reported = b.report?.warnings ?? [];
  // The engine repeats the payout caveat as a note; show it once.
  const notes = (m?.notes ?? []).filter((n) => !(n.includes("ESTIMATE") && reported.some((w) => w.includes("ESTIMATE"))));
  const warnings = [...new Set([...reported, ...notes])];
  const contract = (b.config?.contract ?? m?.contract) || null;
  const currency = "USD";
  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2"><Link href="/strategies?tab=backtests"><ArrowLeft aria-hidden /> All tests</Link></Button>
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:gap-7">
        <div className="flex items-center gap-3.5 sm:contents">
          <Artwork seed={b.name} className="size-16 shrink-0 shadow-[0_8px_40px_rgb(0_0_0/0.35)] sm:size-44" />
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-fg sm:hidden"><FlaskConical className="size-4 text-brand-ink" aria-hidden /> Test on history <BacktestStatus b={b} /></p>
        </div>
        <div className="min-w-0 space-y-3">
        <p className="hidden items-center gap-2 text-sm font-semibold text-fg sm:flex"><FlaskConical className="size-4 text-brand-ink" aria-hidden /> Test on history <BacktestStatus b={b} /></p>
        <h1 className="title-xl text-[2rem] break-words text-fg sm:text-5xl">{b.name}</h1>
        {m && <p className="text-sm text-fg-muted">Net result <PnlText value={m.net_pnl} currency={currency} className="ml-1 text-2xl font-extrabold tracking-tight" /></p>}
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-fg-muted max-sm:flex-col max-sm:items-start">
          {b.data_source === "synthetic" && <Pill tone="warning">Practice (synthetic) data</Pill>}
          <span>{b.symbol} · {b.timeframe} candles · {formatDate(b.start)} – {formatDate(b.end)}</span>
          <span><span aria-hidden className="max-sm:hidden">· </span>starting balance <Money value={b.initial_capital} currency={currency} /></span>
          {contract && <span><span aria-hidden className="max-sm:hidden">· </span>{contractSummary(contract, { currency })}</span>}
          {m?.payout_ratio !== undefined && <span><span aria-hidden className="max-sm:hidden">· </span>payout estimate {m.payout_ratio}</span>}
        </p>
        </div>
      </header>

      {(b.status === "QUEUED" || b.status === "RUNNING") && (
        <Card aria-live="polite">
          <CardContent className="space-y-3">
            <p className="flex items-center gap-2 text-sm font-medium text-fg"><Loader2 className="size-4 animate-spin" aria-hidden /> {b.status === "QUEUED" ? "Waiting for a free worker…" : `Replaying past prices… ${b.progress}%`}</p>
            <Progress value={b.progress} aria-label={`Progress ${b.progress}%`} />
            <p className="text-xs text-fg-muted">This runs on the server — you can leave and come back. The page updates by itself.</p>
          </CardContent>
        </Card>
      )}
      {b.status === "FAILED" && <Notice tone="danger" title="The test failed">{b.error}</Notice>}
      {warnings.length > 0 && (
        <Notice tone="warning" title="Read before trusting these numbers">
          <ul className="list-disc space-y-0.5 pl-5">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Notice>
      )}
      {b.report?.validation ? <ValidationCard v={b.report.validation as ValidationGate} /> : null}
      {m && <MetricsView m={m} currency={currency} />}
      {trades.data && <TradesTable trades={trades.data} symbol={b.symbol} currency={currency} />}
    </div>
  );
}

function Kpi({ label, children, hint }: { label: ReactNode; children: ReactNode; hint?: ReactNode }) {
  return (
    <Card size="sm" className="min-w-0">
      <CardContent>
        <div className="text-xs font-semibold text-fg-muted">{label}</div>
        <div className="num mt-1.5 truncate text-xl font-extrabold tracking-tight text-fg sm:text-2xl">{children}</div>
        {hint && <div className="mt-0.5 text-xs text-fg-subtle">{hint}</div>}
      </CardContent>
    </Card>
  );
}

export function MetricsView({ m, currency }: { m: Metrics; currency?: string }) {
  const equity = useMemo(() => toSeries(m.equity_curve ?? [], (p) => p.t, (p) => p.equity), [m.equity_curve]);
  const drawdown = useMemo(() => toSeries(m.drawdown_curve ?? [], (p) => p.t, (p) => p.dd), [m.drawdown_curve]);
  const streak = m.longest_losing_streak ?? m.max_consecutive_losses;
  return (
    <>
      <section aria-label="Key results" className="grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-4">
        <Kpi label="Net profit / loss" hint={m.return_pct !== null ? `${formatPct(m.return_pct, 2, true)} of the starting balance` : undefined}>
          <PnlText value={m.net_pnl} currency={currency} />
        </Kpi>
        <Kpi label={<Term id="winRate" />} hint={`${m.wins} won · ${m.losses} lost`}>{formatPct(m.win_rate, 1)}</Kpi>
        <Kpi label="Trades" hint={m.outcomes ? Object.entries(m.outcomes).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ") : undefined}>{m.trades}</Kpi>
        <Kpi label={<Term id="profitFactor" />} hint="Money won ÷ money lost; above 1 = more won">{m.profit_factor === null ? "—" : formatNumber(m.profit_factor)}</Kpi>
        <Kpi label={<Term id="drawdown">Max drawdown</Term>} hint={m.max_drawdown !== null ? `${formatCurrency(m.max_drawdown, currency)} from the peak` : undefined}>{formatPct(m.max_drawdown_pct, 1)}</Kpi>
        <Kpi label={<Term id="losingStreak" />}>{streak} in a row</Kpi>
        <Kpi label={<Term id="expectancy" />} hint="Average result per trade">{m.expectancy === null ? "—" : formatSignedCurrency(m.expectancy, currency)}</Kpi>
        <Kpi label="Costs" hint={m.avg_holding_hours !== null ? `Average trade lasted ${formatDuration(m.avg_holding_hours * 3600)}` : undefined}>{formatCurrency(m.total_costs, currency)}</Kpi>
      </section>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Balance over the test</CardTitle><CardDescription>How the balance would have moved, trade by trade.</CardDescription></CardHeader>
          <CardContent>{equity.length > 1 ? <EquityCurve data={equity} label="Balance over the test" format={(v) => formatCurrency(v, currency)} /> : <p className="text-sm text-fg-muted">Not enough trades to draw a curve.</p>}</CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Drawdown</CardTitle><CardDescription>How far below its best point the balance fell.</CardDescription></CardHeader>
          <CardContent>{drawdown.length > 1 ? <EquityCurve data={drawdown} label="Drawdown" variant="drawdown" format={(v) => `${v.toFixed(2)}%`} /> : <p className="text-sm text-fg-muted">No drawdown to show.</p>}</CardContent>
        </Card>
      </div>
      {(m.by_regime?.length ?? 0) > 0 && (
        <Card>
          <CardHeader><CardTitle>By market regime at entry</CardTitle><CardDescription>Trend, sideways or high-volatility conditions when each trade was taken (closed candles only).</CardDescription></CardHeader>
          <CardContent><GroupTable groups={m.by_regime ?? []} currency={currency} label="Regime" /></CardContent>
        </Card>
      )}
      {m.by_symbol.length > 1 && (
        <Card>
          <CardHeader><CardTitle>By market</CardTitle></CardHeader>
          <CardContent><GroupTable groups={m.by_symbol} currency={currency} label="Market" /></CardContent>
        </Card>
      )}
      {m.monthly.length > 1 && (
        <Card>
          <CardHeader><CardTitle>Month by month</CardTitle></CardHeader>
          <CardContent><PnlBars bars={m.monthly.map((x) => ({ label: x.month, value: x.net_pnl, detail: `${x.trades} trades` }))} format={(v) => formatSignedCurrency(v, currency)} label="Monthly net P/L" /></CardContent>
        </Card>
      )}
    </>
  );
}

/** Results per group (regime, market…): the same metrics for each slice. */
export function GroupTable({ groups, currency, label }: { groups: GroupStat[]; currency?: string; label: string }) {
  return (
    <>
    {/* Phones: one card per group with a compact stat grid. */}
    <ul className="space-y-2 sm:hidden" aria-label={`Results by ${label.toLowerCase()}`}>
      {groups.map((g) => (
        <li key={g.key} className="rounded-md bg-surface-raised p-3">
          <div className="flex items-start justify-between gap-3">
            <span className="min-w-0 font-bold break-words text-fg">{humanize(g.key)}</span>
            <span className="shrink-0 text-right">
              <PnlText value={g.net_pnl} currency={currency} className="block font-extrabold" />
              <span className="block text-[11px] text-fg-subtle">net after costs</span>
            </span>
          </div>
          <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-2 text-xs">
            {([
              ["Trades", g.trades],
              ["Win rate", formatPct(g.win_rate, 0)],
              ["Profit factor", g.profit_factor == null ? "—" : formatNumber(g.profit_factor)],
              ["Per trade", g.expectancy == null ? "—" : formatSignedCurrency(g.expectancy, currency)],
              ["Avg R:R", g.avg_rr == null ? "—" : formatNumber(g.avg_rr)],
              ["Max drawdown", g.max_drawdown == null ? "—" : formatCurrency(g.max_drawdown, currency)],
              ["Losing streak", g.longest_losing_streak ?? "—"],
            ] as [string, ReactNode][]).map(([k, v]) => (
              <div key={k} className="min-w-0">
                <dt className="truncate text-fg-subtle">{k}</dt>
                <dd className="num mt-0.5 truncate text-[13px] font-bold text-fg">{v}</dd>
              </div>
            ))}
          </dl>
        </li>
      ))}
    </ul>
    <div className="hidden overflow-x-auto sm:block">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{label}</TableHead><TableHead className="text-right">Trades</TableHead><TableHead className="text-right">Win rate</TableHead>
            <TableHead className="text-right">Profit factor</TableHead><TableHead className="text-right">Per trade</TableHead><TableHead className="text-right">Avg R:R</TableHead>
            <TableHead className="text-right">Max drawdown</TableHead><TableHead className="text-right">Losing streak</TableHead><TableHead className="text-right">Net (after costs)</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.map((g) => (
            <TableRow key={g.key}>
              <TableCell className="font-semibold">{humanize(g.key)}</TableCell>
              <TableCell className="num text-right">{g.trades}</TableCell>
              <TableCell className="num text-right">{formatPct(g.win_rate, 0)}</TableCell>
              <TableCell className="num text-right">{g.profit_factor == null ? "—" : formatNumber(g.profit_factor)}</TableCell>
              <TableCell className="num text-right">{g.expectancy == null ? "—" : formatSignedCurrency(g.expectancy, currency)}</TableCell>
              <TableCell className="num text-right">{g.avg_rr == null ? "—" : formatNumber(g.avg_rr)}</TableCell>
              <TableCell className="num text-right">{g.max_drawdown == null ? "—" : formatCurrency(g.max_drawdown, currency)}</TableCell>
              <TableCell className="num text-right">{g.longest_losing_streak ?? "—"}</TableCell>
              <TableCell className="text-right"><PnlText value={g.net_pnl} currency={currency} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
    </>
  );
}

/** The demo-forward-testing gate: every check with its reason. Never enables anything. */
export function ValidationCard({ v, compact }: { v: ValidationGate; compact?: boolean }) {
  const list = (
    <ul className="space-y-1.5 text-xs sm:space-y-0.5">
      {v.checks.map((c) => (
        <li key={c.name} className={cn("flex gap-1.5 break-words", c.passed ? "text-fg-muted" : "text-fg")}>
          <span aria-hidden className={cn("shrink-0 font-bold", c.passed ? "text-positive" : "text-negative")}>{c.passed ? "✓" : "✗"}</span>
          <span className="min-w-0"><span className="font-semibold">{c.name}</span>: {c.detail}</span>
        </li>
      ))}
    </ul>
  );
  if (compact) {
    return (
      <div className="space-y-1">
        <Pill tone={v.qualifies_for_demo_forward_testing ? "positive" : "warning"}>{v.qualifies_for_demo_forward_testing ? "Qualifies for demo forward testing" : "Not validated for demo forward testing"}</Pill>
        {list}
      </div>
    );
  }
  return (
    <Notice tone={v.qualifies_for_demo_forward_testing ? "success" : "warning"}
      title={v.qualifies_for_demo_forward_testing ? "Qualifies for demo forward testing" : "Does not qualify for demo forward testing"}>
      {list}
      <p className="mt-1 text-xs text-fg-subtle">{v.note}</p>
    </Notice>
  );
}

function TradesTable({ trades, symbol, currency }: { trades: BacktestTrade[]; symbol: string; currency?: string }) {
  const [shown, setShown] = useState(PAGE);
  const rows = trades.slice(0, shown);
  const contract = trades.some((t) => t.contract_type);
  const result = (t: BacktestTrade) => t.outcome === "WON" ? <Pill tone="positive">Won</Pill> : t.outcome === "LOST" ? <Pill tone="negative">Lost</Pill> : t.outcome === "SOLD" ? <Pill>Closed early</Pill> : <span className="text-xs text-fg-muted">{humanize(t.exit_reason)}</span>;
  const dir = (t: BacktestTrade) => {
    const up = t.side === "BUY";
    const label = t.contract_type?.startsWith("CALL") || t.contract_type?.startsWith("PUT") ? (up ? "Rise" : "Fall") : t.contract_type?.startsWith("MULT") ? (up ? "Up" : "Down") : (up ? "Buy" : "Sell");
    return <span className={cn("text-xs font-semibold", up ? "text-positive" : "text-negative")}>{label}</span>;
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>Every simulated trade ({trades.length})</CardTitle>
        <CardDescription>Each trade starts at the open of the candle after the signal — the test never sees the future.</CardDescription>
      </CardHeader>
      <CardContent>
        {trades.length === 0 ? <p className="text-sm text-fg-muted">The rules never matched in this period, so nothing traded.</p> : (
          <>
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Opened</TableHead><TableHead>Direction</TableHead>
                    <TableHead className="text-right">{contract ? "Stake" : "Size"}</TableHead>
                    <TableHead className="text-right">Entry</TableHead><TableHead className="text-right">Exit</TableHead>
                    <TableHead>Result</TableHead><TableHead className="text-right">P/L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((t) => (
                    <TableRow key={t.id}>
                      <TableCell className="text-xs text-fg-muted">{formatTime(t.entry_time)}</TableCell>
                      <TableCell>{dir(t)}</TableCell>
                      <TableCell className="num text-right">{t.stake ? formatCurrency(t.stake, currency) : `${Number(t.volume)} lots`}</TableCell>
                      <TableCell className="num text-right text-fg-muted">{formatPrice(t.entry_price, symbol)}</TableCell>
                      <TableCell className="num text-right text-fg-muted">{formatPrice(t.exit_price, symbol)}</TableCell>
                      <TableCell>{result(t)}</TableCell>
                      <TableCell className="text-right"><PnlText value={t.net_pnl} currency={currency} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <ul className="space-y-2 md:hidden">
              {rows.map((t) => (
                <li key={t.id} className="rounded-md bg-surface-raised px-3.5 py-3">
                  <p className="flex items-center justify-between gap-3">
                    <span className="flex min-w-0 flex-wrap items-center gap-2">{dir(t)} {result(t)}</span>
                    <PnlText value={t.net_pnl} currency={currency} className="shrink-0 text-base font-extrabold" />
                  </p>
                  <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-fg-muted">
                    <span>{formatTime(t.entry_time)}</span>
                    <span>{contract ? "Stake" : "Size"} <span className="num text-fg">{t.stake ? formatCurrency(t.stake, currency) : `${Number(t.volume)} lots`}</span></span>
                    <span className="num">{formatPrice(t.entry_price, symbol)} → {formatPrice(t.exit_price, symbol)}</span>
                  </p>
                </li>
              ))}
            </ul>
            {shown < trades.length && <Button variant="outline" className="mt-3 w-full" onClick={() => setShown(shown + PAGE)}>Show {Math.min(PAGE, trades.length - shown)} more</Button>}
          </>
        )}
      </CardContent>
    </Card>
  );
}
