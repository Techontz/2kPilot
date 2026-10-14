"use client";

import { ChartCandlestick, Radar } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pill } from "@/components/app/badges";
import { PnlText } from "@/components/app/money";
import { EmptyState, ErrorState, SectionHeader } from "@/components/app/states";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useLiveEvent } from "@/components/providers/LiveProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { formatCurrency, formatRelative, formatTime } from "@/lib/format";
import { useApi, useNow } from "@/lib/hooks";
import type { Evaluation, Overview, Paginated, Trade } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  type CandleFeed,
  type ChartTimeframe,
  type InstrumentList,
  pilotSymbol,
  priceDigits,
  robotMarkets,
  secondsToClose,
  TIMEFRAMES,
} from "./chartLogic";
import { LiveChart } from "./LiveChart";

const PREFS_KEY = "tp.charts";

function readPrefs(): { timeframe?: ChartTimeframe; autopilot?: boolean } {
  try {
    return JSON.parse(window.localStorage.getItem(PREFS_KEY) ?? "{}") as { timeframe?: ChartTimeframe; autopilot?: boolean };
  } catch {
    return {}; // storage unavailable: defaults
  }
}

function writePrefs(prefs: { timeframe: ChartTimeframe; autopilot: boolean }): void {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // private mode: the choice simply isn't remembered
  }
}

/**
 * CHARTS — live candles with everything the robot does drawn on them.
 * Autopilot follows the robot on its own: a trade that just closed, else the
 * newest open trade, else each market it watches in turn.
 */
export function ChartsSection() {
  const { account, live } = useAppData();
  const params = useSearchParams();
  const requested = params.get("symbol");
  // Rendered only in the browser (after the session loads), so storage is available.
  const [prefs] = useState(readPrefs);
  const [timeframe, setTimeframe] = useState<ChartTimeframe>(prefs.timeframe && TIMEFRAMES.includes(prefs.timeframe) ? prefs.timeframe : "M5");
  const [autopilot, setAutopilot] = useState(requested === null && prefs.autopilot !== false);
  const [picked, setPicked] = useState<string | null>(requested);
  const [search, setSearch] = useState("");
  const now = useNow(1000);
  const accountId = account?.id;

  useEffect(() => writePrefs({ timeframe, autopilot }), [timeframe, autopilot]);

  const overview = useApi<Overview>(accountId ? "/overview" : null, { account_id: accountId }, live ? 30_000 : 10_000);
  const positions = useApi<Trade[]>(accountId ? "/positions" : null, { account_id: accountId }, 5000);
  const lastClosed = useApi<Paginated<Trade>>(accountId ? "/history" : null, { account_id: accountId, per_page: 1 }, live ? 60_000 : 15_000);
  const instruments = useApi<InstrumentList>(accountId ? "/markets/instruments" : null, { account_id: accountId });

  const open = useMemo(() => positions.data ?? [], [positions.data]);
  const markets = useMemo(() => robotMarkets(overview.data?.active_strategies, open), [overview.data?.active_strategies, open]);
  const piloted = pilotSymbol({ open, markets, lastClosed: lastClosed.data?.data[0], now });
  // Nothing to follow yet: the last market traded, else the first open market.
  const fallback = lastClosed.data?.data[0]?.symbol ?? instruments.data?.instruments.find((i) => i.market_open && i.trade_allowed)?.name ?? null;
  const symbol = (autopilot ? piloted ?? picked : picked ?? markets[0]) ?? fallback;

  const fast = timeframe === "M1" || timeframe === "M5";
  const feed = useApi<CandleFeed>(accountId && symbol ? "/markets/candles" : null, { account_id: accountId, symbol, timeframe, count: 300 }, fast ? 4000 : 30_000);
  const history = useApi<Paginated<Trade>>(accountId && symbol ? "/history" : null, { account_id: accountId, symbol, per_page: 100 }, live ? 60_000 : 15_000);
  const assignment = overview.data?.active_strategies?.find((a) => a.symbol === symbol) ?? null;
  const decisions = useApi<{ evaluations: Paginated<Evaluation> }>(
    assignment ? `/assignments/${assignment.assignment_id}/evaluations` : null,
    { per_page: 5 },
    30_000,
  );

  const reloadTrades = useCallback(() => {
    void positions.reload();
    void history.reload();
    void lastClosed.reload();
  }, [positions, history, lastClosed]);
  useLiveEvent("trade.opened", reloadTrades);
  useLiveEvent("trade.closed", reloadTrades);

  const choose = (s: string) => {
    setPicked(s);
    setAutopilot(false);
    setSearch("");
  };

  const currency = account?.currency ?? "USD";
  const money = useCallback((v: number) => formatCurrency(v, currency), [currency]);
  const instrument = instruments.data?.instruments.find((i) => i.name === symbol);
  const candles = feed.data?.symbol === symbol && feed.data?.timeframe === timeframe ? feed.data.candles : [];
  const digits = priceDigits(instrument, candles);
  const closedHere = useMemo(() => history.data?.data.filter((t) => t.symbol === symbol) ?? [], [history.data, symbol]);
  const openHere = useMemo(() => open.filter((t) => t.symbol === symbol), [open, symbol]);
  const chartTrades = useMemo(() => [...openHere, ...closedHere], [openHere, closedHere]);
  const last = candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  const change = last && prev ? +last.close - +prev.close : null;
  const toClose = secondsToClose(timeframe, now);
  const matches = search.trim().length < 1 ? [] : (instruments.data?.instruments ?? [])
    .filter((i) => `${i.name} ${i.description}`.toLowerCase().includes(search.trim().toLowerCase()))
    .slice(0, 8);

  if (!account) {
    return (
      <Card>
        <EmptyState icon={ChartCandlestick} title="Connect an account to see charts" action={<Button asChild><Link href="/settings/brokers/new">Add broker</Link></Button>}>
          Charts use live prices from your broker.
        </EmptyState>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Charts"
        description="Live prices with every robot trade drawn on them: arrows where it bought or sold, dots with the result where trades closed, and lines for open trades."
        actions={
          <label className="flex items-center gap-3 rounded-full bg-card px-4 py-2 ring-1 ring-line">
            <Radar aria-hidden className={cn("size-4", autopilot ? "text-brand-ink" : "text-fg-subtle")} />
            <span className="text-sm font-semibold text-fg">Autopilot</span>
            <Switch checked={autopilot} onCheckedChange={setAutopilot} aria-label="Autopilot: follow the robot" />
          </label>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        {markets.map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => choose(m)}
            aria-pressed={m === symbol}
            className={cn(
              "flex h-9 items-center gap-2 rounded-full px-4 text-sm font-semibold ring-1 ring-line transition-colors",
              m === symbol ? "bg-primary text-primary-foreground ring-transparent" : "bg-card text-fg-muted hover:text-fg",
            )}
          >
            {m}
            {open.some((t) => t.symbol === m) && <span className="size-1.5 rounded-full bg-positive" aria-label="has an open trade" />}
          </button>
        ))}
        {symbol && !markets.includes(symbol) && (
          <span className="flex h-9 items-center rounded-full bg-primary px-4 text-sm font-semibold text-primary-foreground">{symbol}</span>
        )}
        <div className="relative w-full sm:w-64">
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a market, e.g. EURUSD or R_75" aria-label="Find a market" />
          {matches.length > 0 && (
            <ul className="absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded-lg bg-popover shadow-raised ring-1 ring-line">
              {matches.map((i) => (
                <li key={i.name}>
                  <button type="button" onClick={() => choose(i.name)} className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-surface-hover">
                    <span className="truncate text-fg">{i.description || i.name}</span>
                    <span className="shrink-0 text-xs text-fg-subtle">{i.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {symbol === null ? (
        <Card>
          <EmptyState icon={ChartCandlestick} title="Pick a market" action={<Button asChild variant="outline"><Link href="/strategies">Activate a strategy</Link></Button>}>
            Search for a market above, or activate a strategy: Autopilot then shows the markets the robot trades.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <Card className="min-w-0">
            <CardHeader className="gap-3">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div className="min-w-0">
                  <CardTitle className="flex flex-wrap items-center gap-2 text-xl">
                    {instrument?.description || symbol}
                    <span className="text-sm font-semibold text-fg-subtle">{symbol}</span>
                    {autopilot && piloted === symbol && <Pill tone="primary" dot>Following the robot</Pill>}
                  </CardTitle>
                  <p className="num mt-1 flex items-baseline gap-2">
                    <span className="text-2xl font-extrabold text-fg">{last ? (+last.close).toFixed(digits) : "—"}</span>
                    {change !== null && (
                      <span className={cn("text-sm font-semibold", change > 0 ? "text-positive" : change < 0 ? "text-negative" : "text-fg-muted")}>
                        {change > 0 ? "+" : ""}{change.toFixed(digits)}
                      </span>
                    )}
                    <span className="text-xs text-fg-subtle">Candle closes in {Math.floor(toClose / 60)}:{String(toClose % 60).padStart(2, "0")}</span>
                  </p>
                </div>
                <div role="group" aria-label="Timeframe" className="flex rounded-full bg-muted p-1">
                  {TIMEFRAMES.map((tf) => (
                    <button
                      key={tf}
                      type="button"
                      onClick={() => setTimeframe(tf)}
                      aria-pressed={tf === timeframe}
                      className={cn("h-8 rounded-full px-3 text-xs font-bold transition-colors", tf === timeframe ? "bg-card text-fg shadow-raised" : "text-fg-muted hover:text-fg")}
                    >
                      {tf}
                    </button>
                  ))}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {feed.error && candles.length === 0 ? (
                <ErrorState message={feed.error} onRetry={() => void feed.reload()} />
              ) : candles.length === 0 ? (
                <div className="flex h-[420px] items-center justify-center text-sm text-fg-muted">Loading prices…</div>
              ) : (
                <LiveChart
                  key={`${symbol}-${timeframe}`}
                  candles={candles}
                  trades={chartTrades}
                  digits={digits}
                  timeframe={timeframe}
                  money={money}
                  height={420}
                  label={`${symbol} ${timeframe} chart with robot trades`}
                />
              )}
            </CardContent>
          </Card>

          <div className="space-y-6">
            <RobotNow assignment={assignment} decisions={decisions.data?.evaluations.data ?? null} />
            <OpenTrades trades={openHere} currency={currency} />
            <RecentTrades trades={closedHere.slice(0, 8)} currency={currency} />
          </div>
        </div>
      )}
    </div>
  );
}

function RobotNow({ assignment, decisions }: { assignment: Overview["active_strategies"] extends (infer A)[] | undefined ? A | null : never; decisions: Evaluation[] | null }) {
  const latest = decisions?.[0];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Radar aria-hidden className="size-4 text-brand-ink" /> What the robot is thinking
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!assignment ? (
          <p className="text-fg-muted">No strategy watches this market on this account.</p>
        ) : (
          <>
            <p className="text-fg-muted">{assignment.strategy} · {assignment.contract_summary}</p>
            {latest ? (
              <>
                <div className="flex items-center gap-2">
                  <Pill tone={latest.outcome === "SIGNAL" ? "positive" : "neutral"} dot>{latest.outcome === "SIGNAL" ? "Trade idea" : "Waiting"}</Pill>
                  <span className="text-xs text-fg-subtle">candle {formatTime(latest.bar_time)}</span>
                </div>
                <p className="text-fg">{latest.summary}</p>
                <ul className="space-y-1">
                  {latest.checks.map((c) => (
                    <li key={c.name} className="flex gap-2 text-xs">
                      <span className={c.passed ? "text-positive" : "text-negative"} aria-label={c.passed ? "passed" : "failed"}>{c.passed ? "✓" : "✗"}</span>
                      <span className="text-fg-muted"><span className="font-semibold text-fg">{c.name}:</span> {c.detail}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-fg-muted">No decision yet. The robot checks this market when each candle closes.</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function OpenTrades({ trades, currency }: { trades: Trade[]; currency: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Open on this market</CardTitle>
      </CardHeader>
      <CardContent>
        {trades.length === 0 ? (
          <p className="text-sm text-fg-muted">Nothing open. New trades appear here and on the chart the moment the robot opens them.</p>
        ) : (
          <ul className="divide-y divide-line">
            {trades.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span>
                  <span className={cn("font-bold", t.side === "BUY" ? "text-positive" : "text-negative")}>{t.side === "BUY" ? "Buy" : "Sell"}</span>{" "}
                  <span className="text-fg-muted">{t.stake ? formatCurrency(t.stake, currency) : t.volume} · {formatRelative(t.entry_time)}</span>
                </span>
                <PnlText value={t.unrealized_pnl} currency={currency} className="font-semibold" />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function RecentTrades({ trades, currency }: { trades: Trade[]; currency: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent results here</CardTitle>
      </CardHeader>
      <CardContent>
        {trades.length === 0 ? (
          <p className="text-sm text-fg-muted">No finished trades on this market yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {trades.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="text-fg-muted">
                  <span className={cn("font-semibold", t.side === "BUY" ? "text-positive" : "text-negative")}>{t.side === "BUY" ? "Buy" : "Sell"}</span> · {formatRelative(t.exit_time)}
                </span>
                <PnlText value={t.net_pnl} currency={currency} className="font-semibold" />
              </li>
            ))}
          </ul>
        )}
        <Link href="/history" className="mt-3 inline-block text-sm font-bold text-fg-muted underline-offset-4 hover:text-fg hover:underline">All history</Link>
      </CardContent>
    </Card>
  );
}
