import { describe, expect, it } from "vitest";
import type { Evaluation } from "@/lib/types";
import { candleMinutes, waitingLines } from "./LiveWatch";

const ev = (bar_time: string, checks: Evaluation["checks"] = []): Evaluation => ({ id: 1, bar_time, outcome: "NO_SETUP", summary: "No entry rule matched on this bar.", checks });

describe("LiveWatch helpers", () => {
  it("reads the candle length from the two latest checks", () => {
    expect(candleMinutes([ev("2026-10-12T10:05:00Z"), ev("2026-10-12T10:00:00Z")])).toBe(5);
    expect(candleMinutes([ev("2026-10-12T10:15:00Z"), ev("2026-10-12T10:00:00Z")])).toBe(15);
    expect(candleMinutes([ev("2026-10-12T10:05:00Z")])).toBe(5);
  });

  it("says what each rule is waiting for in plain words", () => {
    const e = ev("2026-10-12T10:05:00Z", [
      { name: "BUY: EMA 9 crosses above EMA 21", passed: false, detail: "EMA 9 (145.210) did not cross above EMA 21 (145.300) on this bar (now below) ✗" },
      { name: "SELL: EMA 9 crosses below EMA 21", passed: false, detail: "EMA 9: not enough data yet ✗" },
    ]);
    expect(waitingLines(e)).toEqual([
      "BUY when EMA 9 crosses above EMA 21 — now below, gap 0.090",
      "SELL: EMA 9: not enough data yet",
    ]);
  });
});
