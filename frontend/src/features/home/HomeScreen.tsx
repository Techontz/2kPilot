"use client";

import { Activity, ArrowRight, CalendarClock, CandlestickChart, CircleAlert, Layers, type LucideIcon, PlugZap, Sigma, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConnectionDot, connectionLabel, Direction, EnvBadge, Pill } from "@/components/app/badges";
import { Money, PnlText } from "@/components/app/money";
import { EmptyState, ErrorState, Notice } from "@/components/app/states";
import { Artwork, SeriesArtwork } from "@/components/app/artwork";
import { Term } from "@/components/app/term";
import { PnlBars } from "@/components/charts/PnlBars";
import { Sparkline } from "@/components/charts/Sparkline";
import { BigTradingButton, useTradingControl } from "@/components/layout/TradingControls";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useLiveRefresh } from "@/components/providers/LiveProvider";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TradeDetailSheet } from "@/features/history/TradeDetailSheet";
import { directionIsUp, sizeText, tradeContractLabel } from "@/lib/contracts";
import { formatCountdown, formatRelative, formatSignedCurrency, formatTime } from "@/lib/format";
import { useApi, useNow } from "@/lib/hooks";
import { deriveRobotStatus } from "@/lib/status";
import type { Blocker, Overview, Trade, TradingStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { isSetupComplete, SetupChecklist } from "./SetupChecklist";

/**
 * HOME — the answer to "what is my bot doing with my money right now?":
 * account & balance, DEMO/LIVE, running or stopped (and why not trading),
 * today's and total P/L, open trades with time left, active strategies, and
 * one big Start/Stop.
 */
export function HomeScreen() {
  const { account, accounts, live, status, statusUnknown } = useAppData();
  const accountId = account?.id;
  const overview = useApi<Overview>(accounts === null ? null : "/overview", { account_id: accountId }, live ? 30_000 : 5000);
  const reload = overview.reload;
  const refresh = useCallback(() => void reload(), [reload]);
  useLiveRefresh(["trading.status", "account.balance", "trade.opened", "trade.closed"], refresh);
  // Start/Stop/mode changes update the shared status at once: refresh the
  // overview's blockers too, so the page never disagrees with the button.
  const statusKey = status ? `${status.kill_switch_engaged}:${status.trading_mode}:${status.platform_halted}` : null;
  const seenStatusKey = useRef(statusKey);
  useEffect(() => {
    if (statusKey === null) return;
    if (seenStatusKey.current !== null && seenStatusKey.current !== statusKey) refresh();
    seenStatusKey.current = statusKey;
  }, [statusKey, refresh]);
  // "Bot running" comes from the same status as the Start/Stop button.
  const robotStatus = statusUnknown ? null : status;
  const [tradeId, setTradeId] = useState<string | null>(null);

  const o = overview.data;
  if (!o) {
    return overview.error ? <ErrorState message={overview.error} onRetry={refresh} /> : <HomeSkeleton />;
  }
  const setup = o.setup;
  const currency = o.account?.currency;

  return (
    <div className="space-y-8">
      <h1 className="sr-only">Home</h1>
      {o.account && <AccountHero overview={o} status={robotStatus} unknown={statusUnknown} />}
      {setup && !isSetupComplete(setup) && <SetupChecklist setup={setup} startAction={<StartButton />} />}
      {o.account ? (
        <>
          <Blockers blockers={o.blockers ?? []} running={!(robotStatus ?? o.robot).kill_switch_engaged} />
          <section aria-label="Profit and loss" className="grid gap-3 sm:gap-4 md:grid-cols-3">
            <Kpi icon={CalendarClock} label={<>Today&apos;s <Term id="realizedPnl">P/L</Term></>} hint="Finished trades since 00:00 UTC">
              <PnlText value={o.figures?.today_pnl} currency={currency} className="text-3xl font-extrabold tracking-tight" />
            </Kpi>
            <Kpi icon={Sigma} label={<>Total <Term id="realizedPnl">realized P/L</Term></>} hint="All finished trades on this account">
              <PnlText value={o.figures?.total_pnl} currency={currency} className="text-3xl font-extrabold tracking-tight" />
            </Kpi>
            <Kpi icon={Activity} label="Open trades" hint={o.figures?.open_positions ? "Current P/L — not final until they finish" : "Nothing open right now"}>
              <span className="flex items-baseline gap-2">
                <span className="num text-3xl font-extrabold tracking-tight text-fg">{o.figures?.open_positions ?? 0}</span>
                {Boolean(o.figures?.open_positions) && <PnlText value={o.figures?.open_pnl} currency={currency} className="text-sm font-bold" />}
              </span>
            </Kpi>
          </section>
          <div className="grid items-start gap-6 lg:grid-cols-3">
            <div className="space-y-6 lg:col-span-2">
              <Positions positions={o.positions ?? []} currency={currency} onOpen={setTradeId} />
              <ResultsChart overview={o} />
            </div>
            <ActiveStrategies overview={o} />
          </div>
        </>
      ) : (
        !setup && (
          <Card>
            <EmptyState icon={PlugZap} title="No account yet" action={<Button asChild><Link href="/settings/brokers/new">Add an account</Link></Button>}>
              Start with Paper (simulated money) or connect a Deriv demo account.
            </EmptyState>
          </Card>
        )
      )}
      <TradeDetailSheet tradeId={tradeId} onClose={() => setTradeId(null)} />
    </div>
  );
}

function StartButton() {
  const { requestStart } = useTradingControl();
  return <Button size="sm" onClick={requestStart} className="bg-positive font-bold text-positive-foreground hover:bg-positive/90">Start trading</Button>;
}

function HomeSkeleton() {
  return (
    <div className="space-y-8" role="status" aria-label="Loading">
      <div className="flex flex-col gap-6 pt-2 sm:flex-row sm:items-end sm:pt-6">
        <Skeleton className="size-36 rounded-lg sm:size-48" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-14 w-72 max-w-full" />
          <Skeleton className="h-3 w-56" />
        </div>
      </div>
      <Skeleton className="h-14 w-56 rounded-full" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-28 rounded-lg" /><Skeleton className="h-28 rounded-lg" /><Skeleton className="h-28 rounded-lg" />
      </div>
      <Skeleton className="h-64 w-full rounded-lg" />
    </div>
  );
}

function AccountHero({ overview: o, status, unknown }: { overview: Overview; status: TradingStatus | null; unknown: boolean }) {
  const a = o.account!;
  const robot = unknown
    ? { label: "Status unknown — reconnecting", tone: "neutral" as const, running: false, detail: "Can't reach the server for the latest status. Stop still works." }
    : deriveRobotStatus(status ?? o.robot);
  const live = a.environment === "LIVE";
  const balance = a.balance ?? o.figures?.balance ?? null;
  const values = (o.balance_history ?? []).map((p) => p.balance);
  const broker = o.broker ?? { name: a.broker, connection_status: a.connection_status, connection_detail: a.connection_detail, last_connected_at: null };
  const kind = live ? "Live account" : a.environment === "DEMO" ? "Demo account" : a.environment === "PAPER" ? "Paper account" : "Account";
  const dot = robot.running ? "bg-positive" : robot.tone === "negative" ? "bg-negative" : robot.tone === "neutral" ? "bg-fg-subtle" : "bg-warning";
  return (
    <section aria-label="Account and bot" className="motion-safe:animate-fade-up">
      <div className="flex flex-col gap-5 pt-2 sm:flex-row sm:items-end sm:gap-7 sm:pt-6">
        <SeriesArtwork values={values} tone={live ? "live" : a.environment === "DEMO" ? "demo" : "paper"}
          className={cn("size-20 shrink-0 rounded-lg shadow-[0_8px_30px_rgb(0_0_0/0.25)] sm:size-44 lg:size-52", live && "ring-4 ring-live")} />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-fg">
            <EnvBadge env={a.environment} />
            <span>{kind}</span>
          </p>
          <p className="mt-3 truncate text-sm font-semibold text-fg-muted sm:text-base">{a.label}</p>
          <div className="mt-1">
            <span className="sr-only">Balance</span>
            <Money value={balance} currency={a.currency} className="title-xl block text-5xl text-fg sm:text-6xl lg:text-7xl" />
          </div>
          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-fg-muted">
            <ConnectionDot status={broker.connection_status} />
            <span className="font-bold text-fg">{broker.name}</span>
            <span aria-hidden>•</span>
            <span>{connectionLabel(broker.connection_status)}</span>
            {broker.connection_status !== "CONNECTED" && broker.connection_detail && <span className="text-xs text-fg-subtle">({broker.connection_detail})</span>}
            {a.broker_account_id && <><span aria-hidden>•</span><span className="mono-id text-xs">{a.broker_account_id}</span></>}
            <span aria-hidden>•</span>
            <span><Term id="balance" /> updated {formatRelative(a.synced_at)}</span>
          </p>
          {live && <p className="mt-2 text-sm font-extrabold text-live">Real money — every loss is real.</p>}
        </div>
      </div>
      <div className="mt-7 flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-6">
        <BigTradingButton className="sm:w-auto sm:min-w-56" />
        <div className="min-w-0">
          <div role="status" aria-live="polite" className="flex items-center gap-2.5 text-sm">
            <span className="relative flex size-3" aria-hidden>
              {robot.running && <span className={cn("absolute inset-0 rounded-full motion-safe:animate-pulse-ring", dot)} />}
              <span className={cn("relative size-3 rounded-full", dot)} />
            </span>
            <span className="text-base font-bold text-fg">{robot.running ? "Bot running" : robot.label === "Trading stopped" ? "Bot stopped" : robot.label}</span>
          </div>
          <p className="mt-1 max-w-md text-[13px] text-fg-muted">{robot.running ? "It keeps trading on the server even when you close this page." : robot.detail}</p>
        </div>
      </div>
    </section>
  );
}

const BLOCKER_ACTION: Record<string, { href: string; label: string } | undefined> = {
  no_active_strategy: { href: "/strategies?tab=mine", label: "Activate a strategy" },
  risk_profile_missing: { href: "/settings?tab=accounts", label: "Choose a risk profile" },
  account_trading_disabled: { href: "/settings?tab=accounts", label: "Turn trading on" },
  broker_disconnected: { href: "/settings?tab=brokers", label: "Check the connection" },
  live_locked: { href: "/settings?tab=accounts", label: "Real-money settings" },
  mode_mismatch: { href: "/settings?tab=accounts", label: "Accounts" },
};

/** Why nothing would trade right now, in plain words, each with the fix. */
function Blockers({ blockers, running }: { blockers: Blocker[]; running: boolean }) {
  const { requestStart } = useTradingControl();
  if (blockers.length === 0) {
    return running ? (
      <Notice tone="success" title="All set — the bot is watching the market">
        Your active strategies are checked every time a candle closes. Every trade passes your risk limits first.
      </Notice>
    ) : null;
  }
  return (
    <Card aria-live="polite" className="ring-warning/25">
      <CardHeader>
        <CardTitle className="flex items-center gap-2.5"><span className="flex size-7 items-center justify-center rounded-full bg-warning-soft"><CircleAlert className="size-4 text-warning" aria-hidden /></span> Nothing will trade right now</CardTitle>
        <CardDescription>
          {blockers.every((b) => b.code === "market_closed")
            ? "Here is why — the bot waits and starts again on its own when the market opens."
            : "Here is why — fix these and the bot can start trading."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {blockers.map((b) => {
            const action = BLOCKER_ACTION[b.code];
            return (
              <li key={`${b.code}:${b.message}`} className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-surface-raised py-2.5 pr-2.5 pl-4">
                <span className="flex min-w-0 items-center gap-2.5 text-sm text-fg"><span aria-hidden className="size-1.5 shrink-0 rounded-full bg-warning" />{b.message}</span>
                {b.code === "trading_stopped" ? (
                  <Button size="sm" onClick={requestStart} className="bg-positive font-bold text-positive-foreground hover:bg-positive/90">Start trading</Button>
                ) : action ? (
                  <Button size="sm" variant="outline" asChild><Link href={action.href}>{action.label} <ArrowRight aria-hidden /></Link></Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function Kpi({ icon: Icon, label, hint, children }: { icon: LucideIcon; label: React.ReactNode; hint?: string; children: React.ReactNode }) {
  return (
    <Card size="sm" className="transition-colors hover:bg-surface-raised">
      <CardContent className="space-y-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-fg-muted">
          <span className="flex size-7 items-center justify-center rounded-full bg-surface-hover"><Icon className="size-3.5 text-fg" aria-hidden /></span>
          {label}
        </p>
        <div>{children}</div>
        {hint && <p className="text-xs text-fg-subtle">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function Positions({ positions, currency, onOpen }: { positions: Trade[]; currency?: string; onOpen: (id: string) => void }) {
  const expiring = positions.some((p) => p.expires_at);
  const now = useNow(1000, expiring);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl font-extrabold">Active trades</CardTitle>
        <CardDescription>Updated live. Tap a trade for details.</CardDescription>
        <CardAction><Button variant="ghost" size="sm" asChild className="font-bold text-fg-muted hover:text-fg"><Link href="/history?tab=open">Show all open <ArrowRight aria-hidden /></Link></Button></CardAction>
      </CardHeader>
      <CardContent>
        {positions.length === 0 ? (
          <EmptyState icon={Layers} title="No open trades" className="py-6">When a strategy opens a trade, it appears here with its time left and current P/L.</EmptyState>
        ) : (
          <ul className="-mx-2" aria-live="polite">
            {positions.map((p, i) => {
              const left = p.contract_family === "RISE_FALL" ? formatCountdown(p.expires_at, now) : null;
              return (
                <li key={p.id}>
                  <button type="button" onClick={() => onOpen(p.id)} className="group flex w-full items-center gap-3 rounded-md px-2 py-2.5 text-left transition-colors hover:bg-surface-hover focus-visible:bg-surface-hover">
                    <span className="num w-5 shrink-0 text-center text-sm text-fg-subtle group-hover:text-fg" aria-hidden>{i + 1}</span>
                    <Countdown trade={p} now={now} />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-bold text-fg">{p.symbol}</span>
                        <Direction trade={p} />
                        <span className="text-xs text-fg-subtle">{tradeContractLabel(p)}</span>
                      </span>
                      <span className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-fg-muted">
                        <span>{p.contract_family && p.contract_family !== "SPOT" ? "Stake" : "Size"} <span className="num text-fg">{sizeText(p, currency)}</span></span>
                        {p.strategy && <span className="truncate">{p.strategy}</span>}
                      </span>
                    </span>
                    {left !== null && (
                      <span className="num shrink-0 text-sm text-fg-muted" aria-label={`Time left ${left}`}>{left}</span>
                    )}
                    <PnlText value={p.unrealized_pnl} currency={currency} className="w-24 shrink-0 text-right text-sm font-bold" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ResultsChart({ overview: o }: { overview: Overview }) {
  const currency = o.account?.currency;
  const daily = o.daily_pnl;
  const bars = useMemo(() => (daily ?? []).map((d) => ({
    label: new Date(`${d.date}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" }),
    value: d.net_pnl,
    detail: `${d.trades} trade${d.trades === 1 ? "" : "s"}`,
  })), [daily]);
  const hasTrades = (daily ?? []).some((d) => d.trades > 0);
  const balances = (o.balance_history ?? []).map((p) => p.balance);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl font-extrabold">Last 30 days</CardTitle>
        <CardDescription>Realized profit or loss per day (UTC), and the balance.</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="daily" className="gap-4">
          <TabsList>
            <TabsTrigger value="daily">Daily P/L</TabsTrigger>
            <TabsTrigger value="balance">Balance</TabsTrigger>
          </TabsList>
          <TabsContent value="daily">
            {hasTrades
              ? <PnlBars bars={bars} label="Daily realized P/L, last 30 days" format={(v) => formatSignedCurrency(v, currency)} height={180} />
              : <EmptyState icon={CandlestickChart} title="No finished trades in the last 30 days" className="py-6" />}
          </TabsContent>
          <TabsContent value="balance">
            {balances.length > 1
              ? <Sparkline values={balances} label="Balance, last 30 days" height={180} tone="neutral" area />
              : <EmptyState icon={CandlestickChart} title="Not enough balance history yet" className="py-6">The balance is recorded as the account syncs.</EmptyState>}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function ActiveStrategies({ overview: o }: { overview: Overview }) {
  const list = o.active_strategies ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl font-extrabold">Active strategies</CardTitle>
        <CardDescription>What the bot is allowed to trade on this account.</CardDescription>
      </CardHeader>
      <CardContent>
        {list.length === 0 ? (
          <EmptyState icon={Layers} title="No strategy active" className="py-6" action={<Button asChild size="sm"><Link href="/strategies">Choose a strategy</Link></Button>}>
            Activate a strategy on this account so the bot has something to trade.
          </EmptyState>
        ) : (
          <ul className="-mx-2 space-y-1">
            {list.map((s) => (
              <li key={s.assignment_id} className="flex gap-3 rounded-md p-2 transition-colors hover:bg-surface-hover">
                <Artwork seed={s.strategy ?? "Strategy"} className="size-12 shrink-0" rounded="rounded" />
                <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center justify-between gap-2">
                  <span className="truncate font-bold text-fg">{s.strategy ?? "Strategy"}</span>
                  <Pill tone="positive" dot>Active</Pill>
                </p>
                <p className="mt-0.5 text-[13px] text-fg-muted"><span className="font-semibold text-fg">{s.symbol}</span> · {s.contract_summary}</p>
                <p className="mt-1 text-xs text-fg-subtle">
                  {s.last_bar_evaluated ? `Last candle checked: ${formatTime(s.last_bar_evaluated)}` : "Waiting for the next candle to close"}
                  {s.last_signal_at ? ` · last signal ${formatRelative(s.last_signal_at)}` : ""}
                </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Rise/Fall: a ring that empties as the contract runs out; other trades get a direction tile. */
function Countdown({ trade, now }: { trade: Trade; now: number }) {
  const start = trade.entry_time ? new Date(trade.entry_time).getTime() : NaN;
  const end = trade.expires_at ? new Date(trade.expires_at).getTime() : NaN;
  const up = directionIsUp(trade);
  if (trade.contract_family !== "RISE_FALL" || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return (
      <span aria-hidden className={cn("flex size-10 shrink-0 items-center justify-center rounded-md", up ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative")}>
        {up ? <TrendingUp className="size-5" /> : <TrendingDown className="size-5" />}
      </span>
    );
  }
  const left = Math.min(1, Math.max(0, (end - now) / (end - start)));
  const r = 16;
  const c = 2 * Math.PI * r;
  return (
    <span aria-hidden className="relative flex size-10 shrink-0 items-center justify-center">
      <svg viewBox="0 0 40 40" className="absolute inset-0 size-full -rotate-90">
        <circle cx="20" cy="20" r={r} fill="none" strokeWidth="3.5" className="stroke-surface-hover" />
        <circle cx="20" cy="20" r={r} fill="none" strokeWidth="3.5" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - left)}
          className={cn("transition-[stroke-dashoffset] duration-1000 ease-linear", up ? "stroke-positive" : "stroke-negative")} />
      </svg>
      {up ? <TrendingUp className="size-4 text-positive" /> : <TrendingDown className="size-4 text-negative" />}
    </span>
  );
}
