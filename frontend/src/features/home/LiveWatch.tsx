"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Pill } from "@/components/app/badges";
import { Sparkline } from "@/components/charts/Sparkline";
import { formatCountdown } from "@/lib/format";
import { useApi, useNow } from "@/lib/hooks";
import type { ActiveStrategy, Candle, Evaluation, Paginated, Quote } from "@/lib/types";
import { cn } from "@/lib/utils";

const TIMEFRAMES: [number, string][] = [[1, "M1"], [5, "M5"], [15, "M15"], [30, "M30"], [60, "H1"], [240, "H4"], [1440, "D1"]];
const CHART_BARS = 48;

/** Candle length in minutes, from the gap between the two latest checked candles (default 5). */
export function candleMinutes(evaluations: Evaluation[]): number {
  if (evaluations.length < 2) return 5;
  const gap = (new Date(evaluations[0]!.bar_time).getTime() - new Date(evaluations[1]!.bar_time).getTime()) / 60_000;
  // Gaps span weekends or missed bars: take the largest timeframe that divides the gap.
  const fit = [...TIMEFRAMES].reverse().find(([m]) => gap >= m && gap % m === 0);
  return fit ? fit[0] : 5;
}

const CROSS = /^(.+?) \(([-\d.]+)\) did not cross (above|below) (.+?) \(([-\d.]+)\).*\(now (above|below|equal to)\)/;

/** One plain line per entry rule: what the bot is waiting for, in words. */
export function waitingLines(e: Evaluation | null | undefined): string[] {
  if (!e) return [];
  return e.checks.map((c) => {
    const m = c.detail.match(CROSS);
    const side = c.name.match(/^(BUY|SELL):/)?.[1];
    if (!m) return `${side ? `${side}: ` : ""}${c.detail.replace(/\s*[✓✗]$/, "")}`;
    const [, fast, a, dir, slow, b, now] = m;
    const gap = Math.abs(Number(a) - Number(b));
    const digits = Math.max(a!.split(".")[1]?.length ?? 0, b!.split(".")[1]?.length ?? 0);
    return `${side ?? "Trade"} when ${fast} crosses ${dir} ${slow} — now ${now}, gap ${gap.toFixed(digits)}`;
  });
}

/** What the bot sees on one active strategy: live price, recent candles and its latest check. */
export function LiveWatch({ accountId, strategy: s }: { accountId: string; strategy: ActiveStrategy }) {
  const evals = useApi<{ evaluations: Paginated<Evaluation> }>(`/assignments/${s.assignment_id}/evaluations`, { per_page: 2 }, 30_000);
  const list = evals.data?.evaluations.data ?? [];
  const minutes = candleMinutes(list);
  const tf = TIMEFRAMES.find(([m]) => m === minutes)?.[1] ?? "M5";
  const quotes = useApi<{ quotes: Record<string, Quote> }>("/markets/quotes", { account_id: accountId, symbols: s.symbol }, 5_000);
  const chart = useApi<{ candles: Candle[] }>(`/markets/instruments/${encodeURIComponent(s.symbol)}`, { account_id: accountId, timeframe: tf }, 60_000);
  const now = useNow(1000);

  const quote = quotes.data?.quotes[s.symbol];
  const price = quote ? (Number(quote.bid) + Number(quote.ask)) / 2 : null;
  const digits = quote ? Math.max(quote.bid.split(".")[1]?.length ?? 0, 2) : 2;
  const move = usePriceMove(price);
  const closes = (chart.data?.candles ?? []).slice(-CHART_BARS).map((c) => Number(c.close));
  if (price !== null && closes.length) closes.push(price);

  const latest = list[0] ?? null;
  const ms = minutes * 60_000;
  const nextClose = new Date(Math.floor(now / ms) * ms + ms).toISOString();
  const lines = latest?.outcome === "NO_SETUP" ? waitingLines(latest) : [];

  return (
    <div className="mt-2 rounded-md p-3 ring-1 ring-line" aria-label={`Live view of ${s.symbol}`}>
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn("inline-flex items-center gap-1 font-mono text-lg font-bold tabular-nums transition-colors",
          move === "up" ? "text-positive" : move === "down" ? "text-negative" : "text-fg")}>
          {price === null ? "—" : price.toFixed(digits)}
          {move === "up" && <ArrowUp className="size-4" aria-label="rising" />}
          {move === "down" && <ArrowDown className="size-4" aria-label="falling" />}
        </span>
        <span className="text-xs text-fg-subtle">Next check in {formatCountdown(nextClose, now) ?? "—"}</span>
      </div>
      {closes.length > 1 && <Sparkline values={closes} label={`${s.symbol}, last ${closes.length} ${tf} candles`} height={56} className="mt-2" />}
      {latest && (
        <div className="mt-2 space-y-1">
          <p className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
            <Pill tone={latest.outcome === "SIGNAL" ? "positive" : "neutral"}>
              {latest.outcome === "SIGNAL" ? "Signal" : latest.outcome === "NO_SETUP" ? "Waiting" : "Not enough data"}
            </Pill>
            Last check {new Date(latest.bar_time).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
          </p>
          {lines.length > 0
            ? lines.map((l) => <p key={l} className="text-xs leading-snug break-words text-fg-muted">{l}</p>)
            : <p className="text-xs leading-snug break-words text-fg-muted">{latest.summary}</p>}
        </div>
      )}
    </div>
  );
}

/** "up" / "down" for a moment after the price changes. */
function usePriceMove(price: number | null): "up" | "down" | null {
  const prev = useRef<number | null>(null);
  const [move, setMove] = useState<"up" | "down" | null>(null);
  useEffect(() => {
    if (price === null) return;
    if (prev.current !== null && price !== prev.current) setMove(price > prev.current ? "up" : "down");
    prev.current = price;
  }, [price]);
  return move;
}
