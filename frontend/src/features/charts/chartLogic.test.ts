import { describe, expect, it } from "vitest";
import type { ActiveStrategy, Candle, Trade } from "@/lib/types";
import { ema, pilotSymbol, PILOT_ROTATE_MS, priceDigits, robotMarkets, secondsToClose, toBars, tradeLines, tradeMarkers } from "./chartLogic";

const trade = (over: Partial<Trade>): Trade =>
  ({ id: "t", symbol: "R_10", side: "BUY", status: "OPEN", entry_price: "100", entry_time: "2026-10-14T03:41:10Z", exit_time: null, exit_price: null,
    stop_loss: null, take_profit: null, net_pnl: null, stake: "10", ...over }) as Trade;
const active = (symbol: string) => ({ symbol }) as ActiveStrategy;
const candle = (time: string, close: string): Candle => ({ time, open: close, high: close, low: close, close, volume: 0 });
const money = (v: number) => `$${Math.abs(v).toFixed(2)}`.replace("$", v < 0 ? "−$" : "$");

describe("robotMarkets", () => {
  it("lists open trades first, then active strategies, without repeats", () => {
    const open = [trade({ symbol: "R_25", entry_time: "2026-10-14T01:00:00Z" }), trade({ symbol: "R_50", entry_time: "2026-10-14T02:00:00Z" })];
    expect(robotMarkets([active("R_10"), active("R_25")], open)).toEqual(["R_50", "R_25", "R_10"]);
  });
});

describe("pilotSymbol", () => {
  const now = Date.parse("2026-10-14T04:00:00Z");
  it("shows a trade that just closed, then the newest open trade, then rotates", () => {
    const closed = trade({ symbol: "R_25", status: "CLOSED", exit_time: "2026-10-14T03:59:30Z" });
    expect(pilotSymbol({ open: [trade({ symbol: "R_10" })], markets: ["R_10"], lastClosed: closed, now })).toBe("R_25");
    const old = { ...closed, exit_time: "2026-10-14T03:50:00Z" };
    expect(pilotSymbol({ open: [trade({ symbol: "R_10" })], markets: ["R_10", "R_25"], lastClosed: old, now })).toBe("R_10");
    const a = pilotSymbol({ open: [], markets: ["R_10", "R_25"], lastClosed: old, now });
    const b = pilotSymbol({ open: [], markets: ["R_10", "R_25"], lastClosed: old, now: now + PILOT_ROTATE_MS });
    expect(new Set([a, b])).toEqual(new Set(["R_10", "R_25"]));
    expect(pilotSymbol({ open: [], markets: [], lastClosed: null, now })).toBeNull();
  });
});

describe("bars and indicators", () => {
  it("drops duplicate or out-of-order candles", () => {
    const bars = toBars([candle("2026-10-14T03:40:00Z", "1"), candle("2026-10-14T03:40:00Z", "2"), candle("2026-10-14T03:35:00Z", "3"), candle("2026-10-14T03:45:00Z", "4")]);
    expect(bars.map((b) => b.close)).toEqual([1, 4]);
  });

  it("computes an EMA seeded with the simple average", () => {
    const bars = toBars(["1", "2", "3", "4"].map((c, i) => candle(`2026-10-14T03:4${i}:00Z`, c)));
    const line = ema(bars, 3);
    expect(line).toHaveLength(2);
    expect(line[0]!.value).toBe(2);
    expect(line[1]!.value).toBe(3); // 4 * 0.5 + 2 * 0.5
    expect(ema(bars, 10)).toEqual([]);
  });

  it("uses the broker's digits, else the candles' decimals", () => {
    expect(priceDigits({ digits: 3 } as never, [])).toBe(3);
    expect(priceDigits(undefined, [candle("2026-10-14T03:40:00Z", "1.10512")])).toBe(5);
    expect(priceDigits(undefined, [candle("2026-10-14T03:40:00Z", "6500")])).toBe(2);
  });

  it("counts down to the bar close", () => {
    expect(secondsToClose("M5", Date.parse("2026-10-14T03:41:10Z"))).toBe(230);
  });
});

describe("trade markers", () => {
  const bars = toBars(["03:35", "03:40", "03:45"].map((t) => candle(`2026-10-14T${t}:00Z`, "100")));
  it("marks the entry and exit bars with the result", () => {
    const won = trade({ status: "CLOSED", entry_time: "2026-10-14T03:36:10Z", exit_time: "2026-10-14T03:47:00Z", net_pnl: "7.9" });
    const lost = trade({ side: "SELL", status: "CLOSED", entry_time: "2026-10-14T03:41:00Z", exit_time: "2026-10-14T03:44:59Z", net_pnl: "-10" });
    expect(tradeMarkers([won, lost], bars, "M5", money)).toEqual([
      { time: bars[0]!.time, position: "belowBar", shape: "arrowUp", tone: "positive", text: "Buy $10.00" },
      { time: bars[1]!.time, position: "aboveBar", shape: "arrowDown", tone: "negative", text: "Sell $10.00" },
      { time: bars[1]!.time, position: "belowBar", shape: "circle", tone: "negative", text: "−$10.00" },
      { time: bars[2]!.time, position: "aboveBar", shape: "circle", tone: "positive", text: "+$7.90" },
    ]);
  });

  it("leaves out trades outside the loaded bars", () => {
    expect(tradeMarkers([trade({ entry_time: "2026-10-13T10:00:00Z" })], bars, "M5", money)).toEqual([]);
  });

  it("draws entry, stop and target lines for an open trade", () => {
    expect(tradeLines(trade({ entry_spot: "101.5", stop_loss: "99", take_profit: "106" })).map((l) => [l.kind, l.price])).toEqual([
      ["entry", 101.5], ["stop", 99], ["target", 106],
    ]);
  });
});
