import type { ActiveStrategy, Candle, Instrument, Trade } from "@/lib/types";

export const TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"] as const;
export type ChartTimeframe = (typeof TIMEFRAMES)[number];

export const TIMEFRAME_SECONDS: Record<ChartTimeframe, number> = {
  M1: 60,
  M5: 300,
  M15: 900,
  H1: 3600,
  H4: 14_400,
  D1: 86_400,
};

/** GET /markets/instruments */
export interface InstrumentList {
  instruments: Instrument[];
  sync_error: string | null;
}

/** GET /markets/candles */
export interface CandleFeed {
  symbol: string;
  timeframe: ChartTimeframe;
  candles: Candle[];
  simulated: boolean;
}

/** How long Autopilot shows each robot market when nothing is open. */
export const PILOT_ROTATE_MS = 20_000;
/** How long Autopilot stays on a market after one of its trades closed. */
export const PILOT_RESULT_MS = 60_000;

/** The robot's markets: open trades first (newest first), then active strategies. */
export function robotMarkets(active: ActiveStrategy[] | undefined, open: Trade[] | null | undefined): string[] {
  const out: string[] = [];
  for (const t of newestFirst(open ?? [])) if (!out.includes(t.symbol)) out.push(t.symbol);
  for (const a of active ?? []) if (!out.includes(a.symbol)) out.push(a.symbol);
  return out;
}

/**
 * The market Autopilot shows right now:
 * 1. a trade that just closed (for a minute, so its result can be seen),
 * 2. else the newest open trade,
 * 3. else each robot market in turn.
 */
export function pilotSymbol({
  open,
  markets,
  lastClosed,
  now,
}: {
  open: Trade[] | null | undefined;
  markets: string[];
  lastClosed: Trade | null | undefined;
  now: number;
}): string | null {
  const closedAt = lastClosed?.exit_time ? Date.parse(lastClosed.exit_time) : NaN;
  if (lastClosed && now - closedAt >= 0 && now - closedAt < PILOT_RESULT_MS) return lastClosed.symbol;
  const newest = newestFirst(open ?? [])[0];
  if (newest) return newest.symbol;
  if (markets.length === 0) return null;
  return markets[Math.floor(now / PILOT_ROTATE_MS) % markets.length]!;
}

function newestFirst(trades: Trade[]): Trade[] {
  return [...trades].sort((a, b) => (Date.parse(b.entry_time ?? "") || 0) - (Date.parse(a.entry_time ?? "") || 0));
}

export interface Bar {
  time: number; // unix seconds, bar open
  open: number;
  high: number;
  low: number;
  close: number;
}

/** Candles as strictly increasing bars (duplicates and out-of-order bars dropped). */
export function toBars(candles: Candle[]): Bar[] {
  const bars: Bar[] = [];
  for (const k of candles) {
    const time = Math.floor(Date.parse(k.time) / 1000);
    if (!Number.isFinite(time) || (bars.length && time <= bars[bars.length - 1]!.time)) continue;
    bars.push({ time, open: +k.open, high: +k.high, low: +k.low, close: +k.close });
  }
  return bars;
}

/** Exponential moving average of the closes; one point per bar from the `period`-th bar on. */
export function ema(bars: Bar[], period: number): { time: number; value: number }[] {
  if (bars.length < period) return [];
  const k = 2 / (period + 1);
  let value = bars.slice(0, period).reduce((s, b) => s + b.close, 0) / period;
  const out = [{ time: bars[period - 1]!.time, value }];
  for (let i = period; i < bars.length; i++) {
    value = bars[i]!.close * k + value * (1 - k);
    out.push({ time: bars[i]!.time, value });
  }
  return out;
}

/** Decimal places to show: the broker's digits, else the most the candles use (at most 5). */
export function priceDigits(instrument: Instrument | undefined, candles: Candle[]): number {
  if (instrument && Number.isInteger(instrument.digits)) return instrument.digits;
  let digits = 2;
  for (const k of candles.slice(-20)) {
    const decimals = String(k.close).split(".")[1]?.length ?? 0;
    digits = Math.max(digits, decimals);
  }
  return Math.min(digits, 5);
}

export interface TradeMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown" | "circle";
  tone: "positive" | "negative" | "neutral";
  text: string;
}

/**
 * Where the robot bought, sold and closed, on the bar each happened in.
 * Markers outside the loaded bars are left out (the chart cannot place them).
 */
export function tradeMarkers(trades: Trade[], bars: Bar[], timeframe: ChartTimeframe, money: (v: number) => string): TradeMarker[] {
  if (bars.length === 0) return [];
  const step = TIMEFRAME_SECONDS[timeframe];
  const first = bars[0]!.time;
  const last = bars[bars.length - 1]!.time;
  const barOf = (iso: string | null): number | null => {
    const t = iso ? Math.floor(Date.parse(iso) / 1000) : NaN;
    if (!Number.isFinite(t)) return null;
    const bar = t - (((t % step) + step) % step);
    return bar >= first && bar <= last ? bar : null;
  };
  const out: TradeMarker[] = [];
  for (const t of trades) {
    const buy = t.side === "BUY";
    const opened = barOf(t.entry_time);
    if (opened !== null) {
      out.push({
        time: opened,
        position: buy ? "belowBar" : "aboveBar",
        shape: buy ? "arrowUp" : "arrowDown",
        tone: buy ? "positive" : "negative",
        text: `${buy ? "Buy" : "Sell"}${t.stake ? ` ${money(+t.stake)}` : ""}`,
      });
    }
    const closed = t.status === "CLOSED" ? barOf(t.exit_time) : null;
    if (closed !== null) {
      const pnl = t.net_pnl === null ? null : +t.net_pnl;
      out.push({
        time: closed,
        position: buy ? "aboveBar" : "belowBar",
        shape: "circle",
        tone: pnl === null || pnl === 0 ? "neutral" : pnl > 0 ? "positive" : "negative",
        text: pnl === null ? "Closed" : `${pnl > 0 ? "+" : ""}${money(pnl)}`,
      });
    }
  }
  return out.sort((a, b) => a.time - b.time);
}

/** Price lines for an open trade: where it entered, and its stop and target if it has them. */
export function tradeLines(t: Trade): { price: number; kind: "entry" | "stop" | "target"; title: string }[] {
  const lines: { price: number; kind: "entry" | "stop" | "target"; title: string }[] = [];
  const entry = Number(t.entry_spot ?? t.entry_price);
  if (Number.isFinite(entry) && entry > 0) lines.push({ price: entry, kind: "entry", title: t.side === "BUY" ? "Bought" : "Sold" });
  const stop = t.stop_loss === null ? NaN : Number(t.stop_loss);
  if (Number.isFinite(stop) && stop > 0) lines.push({ price: stop, kind: "stop", title: "Stop loss" });
  const target = t.take_profit === null ? NaN : Number(t.take_profit);
  if (Number.isFinite(target) && target > 0) lines.push({ price: target, kind: "target", title: "Take profit" });
  return lines;
}

/** Seconds until the current bar closes (when the robot next checks its strategies). */
export function secondsToClose(timeframe: ChartTimeframe, nowMs: number): number {
  const step = TIMEFRAME_SECONDS[timeframe];
  const now = Math.floor(nowMs / 1000);
  return step - (now % step);
}
