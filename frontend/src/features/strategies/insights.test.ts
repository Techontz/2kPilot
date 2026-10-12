import { describe, expect, it } from "vitest";
import type { Evaluation, Strategy } from "@/lib/types";
import { allowedFamilies, allowedSymbols, contractSupportText, decisionOf, familiesFor, gateSummary, parameterRows, regimeOf, riskCaps } from "./insights";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: "s1",
    key: "adaptive_trend_momentum",
    name: "Adaptive Trend & Momentum",
    description: "Uses trend, momentum, and volatility filters to identify potential trading opportunities while controlling risk.",
    built_in: true,
    code_version: "1.0.0",
    parameter_schema: { properties: { min_adx: { type: "number", description: "Minimum trend-timeframe ADX for a trend." } } },
    versions: [{ id: "v1", version: 1, code_version: "1.0.0", parameters: { min_adx: 25, allow_long: true, risk_per_trade_pct: 0.5, max_daily_loss_pct: 2, max_open_positions: 1 }, notes: "", created_at: "" }],
    assignments: [],
    live_trades: 0,
    live_net_pnl: 0,
    last_backtest: null,
    ...overrides,
  };
}

function evaluation(overrides: Partial<Evaluation>): Evaluation {
  return { id: 1, bar_time: "2026-10-11T08:00:00Z", outcome: "NO_SETUP", summary: "", checks: [], ...overrides };
}

describe("contract and market support", () => {
  it("reads the catalogue first, then the stored details", () => {
    expect(allowedFamilies(strategy({ contract_families: ["SPOT", "MULTIPLIER"] }))).toEqual(["SPOT", "MULTIPLIER"]);
    expect(allowedFamilies(strategy({ details: { supported_contract_families: ["MULTIPLIER"] } }))).toEqual(["MULTIPLIER"]);
    expect(allowedFamilies(strategy())).toBeNull();
    expect(allowedSymbols(strategy({ symbols: ["R_10", "R_25"] }))).toEqual(["R_10", "R_25"]);
  });

  it("never offers Rise/Fall to a strategy that needs a stop and a target", () => {
    const s = strategy({ contract_families: ["SPOT", "MULTIPLIER"] });
    expect(familiesFor(s, ["RISE_FALL", "MULTIPLIER"])).toEqual(["MULTIPLIER"]);
    expect(familiesFor(strategy(), ["RISE_FALL", "MULTIPLIER"])).toEqual(["RISE_FALL", "MULTIPLIER"]);
    expect(contractSupportText(["SPOT", "MULTIPLIER"])).toBe("Multiplier (Deriv) · Spot (Paper) · not Rise/Fall");
    expect(contractSupportText(null)).toBe("Every contract type");
  });
});

describe("latest decision and regime", () => {
  it("reads the regime from the Market regime check", () => {
    const e = evaluation({ outcome: "SIGNAL", summary: "BUY signal: TREND_UP on M15", checks: [{ name: "Market regime", passed: true, detail: "TREND_UP — ADX 31.2 ≥ 25, EMA20 above EMA50 and rising" }] });
    expect(regimeOf(e)).toEqual({ regime: "TREND_UP", reason: "ADX 31.2 ≥ 25, EMA20 above EMA50 and rising" });
    expect(decisionOf(e)).toBe("BUY");
  });

  it("explains NO_TRADE with the regime", () => {
    const e = evaluation({ summary: "No trade: regime SIDEWAYS — ADX 14.2 below 20: no trend", checks: [{ name: "Market regime", passed: false, detail: "SIDEWAYS — ADX 14.2 below 20: no trend" }] });
    expect(regimeOf(e)?.regime).toBe("SIDEWAYS");
    expect(decisionOf(e)).toBe("NO_TRADE");
    expect(decisionOf(evaluation({ outcome: "SIGNAL", summary: "SELL signal: TREND_DOWN" }))).toBe("SELL");
    expect(regimeOf(evaluation({ summary: "Not enough data" }))).toBeNull();
    expect(decisionOf(null)).toBeNull();
  });
});

describe("parameters and risk", () => {
  it("separates the strategy's risk caps from its parameters", () => {
    const s = strategy();
    expect(riskCaps(s.versions[0]!.parameters)).toEqual([
      { key: "risk_per_trade_pct", label: "Risk per trade (max, % of balance)", value: "0.5%" },
      { key: "max_daily_loss_pct", label: "Daily loss limit (max, %)", value: "2%" },
      { key: "max_open_positions", label: "Open positions (max)", value: "1" },
    ]);
    expect(parameterRows(s)).toEqual([
      { key: "min_adx", label: "Min adx", value: "25", description: "Minimum trend-timeframe ADX for a trend." },
      { key: "allow_long", label: "Allow long", value: "yes", description: undefined },
    ]);
    expect(parameterRows(strategy({ key: "rules" }))).toEqual([]);
  });
});

describe("validation gate", () => {
  it("states the verdict without claiming profit", () => {
    expect(gateSummary(null)).toBeNull();
    expect(gateSummary({ qualifies_for_demo_forward_testing: false, checks: [], reasons: ["57 out-of-sample trades (need at least 100)"], note: "" })).toEqual({
      ok: false,
      text: "Does not qualify for demo forward testing: 57 out-of-sample trades (need at least 100).",
    });
    expect(gateSummary({ qualifies_for_demo_forward_testing: true, checks: [], reasons: [], note: "" })?.text).toContain("not a claim of profit");
  });
});
