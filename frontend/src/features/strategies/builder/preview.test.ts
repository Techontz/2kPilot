import { describe, expect, it } from "vitest";
import type { Condition, Operand, RuleSet, RulesCatalog } from "@/lib/types";
import catalogJson from "./__fixtures__/catalog.json";
import templates from "./__fixtures__/templates.json";
import { conditionText, contractExitText, fmtNumber, groupText, operandLabel, ruleLines, rulesText, stopText, targetText } from "./preview";

const catalog = catalogJson as unknown as RulesCatalog;

const ema = (period: number, source?: string): Operand => ({ indicator: "ema", params: source ? { period, source } : { period } });
const rsi = { indicator: "rsi", params: { period: 14 } };

describe("fmtNumber (Python {:g})", () => {
  it.each([
    [30, "30"],
    [30.0, "30"],
    [0.25, "0.25"],
    [1.5, "1.5"],
    [-2, "-2"],
    [0.0001, "0.0001"],
    [0.00001, "1e-05"],
    [123456.7, "123457"],
    [1.23456789, "1.23457"],
    [999999.4, "999999"],
    [1_000_000, "1,000,000"],
    [-2_500_000, "-2,500,000"],
    [0, "0"],
  ])("%s → %s", (input, expected) => {
    expect(fmtNumber(input)).toBe(expected);
  });
});

describe("operandLabel", () => {
  it("labels prices, numbers and indicators like the engine", () => {
    expect(operandLabel({ price: "close" })).toBe("the close");
    expect(operandLabel({ value: 70 })).toBe("70");
    expect(operandLabel({ value: 0.5 })).toBe("0.5");
    expect(operandLabel(ema(20), catalog)).toBe("EMA 20");
    expect(operandLabel(ema(20, "high"), catalog)).toBe("EMA 20 of high");
    expect(operandLabel({ indicator: "sma", params: { period: 200, source: "close" } }, catalog)).toBe("SMA 200");
    expect(operandLabel(rsi, catalog)).toBe("RSI 14");
    expect(operandLabel({ indicator: "atr", params: {} }, catalog)).toBe("ATR 14");
    expect(operandLabel({ indicator: "roc", params: { period: 5 } }, catalog)).toBe("ROC 5");
  });

  it("fills omitted settings with catalogue defaults and tolerates nulls / []", () => {
    expect(operandLabel({ indicator: "ema" }, catalog)).toBe("EMA 20");
    expect(operandLabel({ price: null, value: null, indicator: "rsi", params: null, output: null }, catalog)).toBe("RSI 14");
    expect(operandLabel({ price: "low", value: null, indicator: null, params: [] as unknown as Record<string, number>, output: null }, catalog)).toBe("the low");
  });

  it("names MACD outputs", () => {
    const p = { fast: 12, slow: 26, signal: 9 };
    expect(operandLabel({ indicator: "macd", params: p }, catalog)).toBe("MACD line (12, 26, 9)");
    expect(operandLabel({ indicator: "macd", params: p, output: "signal" }, catalog)).toBe("MACD signal line (12, 26, 9)");
    expect(operandLabel({ indicator: "macd", params: p, output: "histogram" }, catalog)).toBe("MACD histogram (12, 26, 9)");
  });

  it("names Bollinger bands and %B", () => {
    const p = { period: 20, stddev: 2 };
    expect(operandLabel({ indicator: "bollinger", params: p }, catalog)).toBe("the upper Bollinger band (20, 2)");
    expect(operandLabel({ indicator: "bollinger", params: { period: 20, stddev: 2.5 }, output: "lower" }, catalog)).toBe("the lower Bollinger band (20, 2.5)");
    expect(operandLabel({ indicator: "bollinger", params: p, output: "percent_b" }, catalog)).toBe("Bollinger %B (20, 2)");
  });

  it("describes Donchian highs and lows", () => {
    expect(operandLabel({ indicator: "highest", params: { period: 20 } }, catalog)).toBe("the highest high of the previous 20 bars");
    expect(operandLabel({ indicator: "lowest", params: { period: 10, source: "close" } }, catalog)).toBe("the lowest close of the previous 10 bars");
  });
});

describe("conditionText", () => {
  it("joins left, operator and right", () => {
    expect(conditionText({ left: ema(9), op: "crosses_above", right: ema(21) }, catalog)).toBe("EMA 9 crosses above EMA 21");
    expect(conditionText({ left: rsi, op: "lte", right: { value: 30 } }, catalog)).toBe("RSI 14 is at or below 30");
  });

  it("handles between", () => {
    expect(conditionText({ left: rsi, op: "between", low: { value: 40 }, high: { value: 60 } }, catalog)).toBe("RSI 14 is between 40 and 60");
  });

  it("mentions within_bars only above 1", () => {
    const c: Condition = { left: ema(9), op: "crosses_above", right: ema(21), within_bars: 3 };
    expect(conditionText(c, catalog)).toBe("EMA 9 crosses above EMA 21 within the last 3 bars");
    expect(conditionText({ ...c, within_bars: 1 }, catalog)).toBe("EMA 9 crosses above EMA 21");
    expect(conditionText({ ...c, within_bars: null }, catalog)).toBe("EMA 9 crosses above EMA 21");
  });
});

describe("groupText", () => {
  const a: Condition = { left: rsi, op: "lt", right: { value: 30 } };
  const b: Condition = { left: { price: "close" }, op: "gt", right: ema(50) };
  const c: Condition = { left: ema(9), op: "crosses_above", right: ema(21) };

  it("joins two with and / or", () => {
    expect(groupText({ all: [a, b] }, catalog)).toBe("RSI 14 is below 30 and the close is above EMA 50");
    expect(groupText({ any: [a, b], all: null }, catalog)).toBe("RSI 14 is below 30 or the close is above EMA 50");
  });

  it("uses the Oxford comma for 'all' groups of three only", () => {
    expect(groupText({ all: [a, b, c] }, catalog)).toBe("RSI 14 is below 30, the close is above EMA 50, and EMA 9 crosses above EMA 21");
    expect(groupText({ any: [a, b, c] }, catalog)).toBe("RSI 14 is below 30, the close is above EMA 50 or EMA 9 crosses above EMA 21");
  });
});

describe("stop and target text", () => {
  it("formats every type", () => {
    expect(stopText({ type: "atr", atr_period: 14, multiple: 2 })).toBe("2 × ATR 14");
    expect(stopText({ type: "pips", pips: 15.5 })).toBe("15.5 pips");
    expect(targetText({ type: "rr", ratio: 1.5 })).toBe("1.5 × the stop distance");
    expect(targetText({ type: "atr", atr_period: 10, multiple: 3 })).toBe("3 × ATR 10");
    expect(targetText({ type: "pips", pips: 40 })).toBe("40 pips");
  });
});

describe("ruleLines", () => {
  it.each(templates.map((t) => [t.slug, t] as const))("reproduces the stored rules_text of %s", (_slug, t) => {
    expect(rulesText(t.parameters as unknown as RuleSet, catalog)).toBe(t.rules_text);
  });

  it("matches the documented example, filters and 'no target'", () => {
    const rules: RuleSet = {
      schema_version: 1,
      timeframe: "H1",
      entry: { buy: { all: [{ left: ema(20), op: "crosses_above", right: ema(50) }, { left: rsi, op: "lt", right: { value: 70 } }] } },
      filters: [
        { left: { price: "close" }, op: "gt", right: { indicator: "sma", params: { period: 200 } } },
        { left: rsi, op: "between", low: { value: 30 }, high: { value: 70 } },
      ],
      exit: { stop: { type: "pips", pips: 20 }, target: null },
    };
    expect(ruleLines(rules, catalog)).toEqual([
      "Buy when EMA 20 crosses above EMA 50 and RSI 14 is below 70.",
      "Only trade when the close is above SMA 200 and RSI 14 is between 30 and 70.",
      "Stop: 20 pips from the entry; no target (Spot and Multiplier trades).",
      "Checked on every closed H1 bar.",
    ]);
  });

  it("uses the engine defaults when exit is omitted", () => {
    const rules: RuleSet = { schema_version: 1, timeframe: "M5", entry: { sell: { any: [{ left: rsi, op: "crosses_below", right: { value: 70 } }] } } };
    expect(ruleLines(rules, catalog)).toEqual([
      "Sell when RSI 14 crosses below 70.",
      "Stop: 2 × ATR 14 from the entry; target: 2 × the stop distance (Spot and Multiplier trades).",
      "Checked on every closed M5 bar.",
    ]);
  });
});

describe("contractExitText", () => {
  it("uses the catalogue notes, with a fallback", () => {
    expect(contractExitText("RISE_FALL", catalog)).toBe(catalog.contract_notes.RISE_FALL);
    expect(contractExitText("RISE_FALL")).toMatch(/run to expiry/);
    expect(contractExitText("MULTIPLIER")).toMatch(/close the contract early/);
    expect(contractExitText("SPOT")).toMatch(/Paper only/);
  });
});
