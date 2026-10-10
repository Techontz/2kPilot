import { describe, expect, it } from "vitest";
import type { RuleSet, RulesCatalog } from "@/lib/types";
import catalogJson from "./__fixtures__/catalog.json";
import templates from "./__fixtures__/templates.json";
import {
  type BuilderState,
  type ConditionState,
  cloneCondition,
  conditionProblems,
  conditionToRules,
  defaultCondition,
  defaultParams,
  defaultState,
  findIndicator,
  findProblems,
  formatBound,
  indicatorOperand,
  localProblems,
  mirrorCondition,
  newId,
  operandKey,
  operandProblems,
  operandScale,
  operandToRules,
  parseNumber,
  previewLines,
  priceOperand,
  rulesToState,
  scaleMeaning,
  stateToRules,
  stopToRules,
  targetToRules,
  totalConditions,
  valueOperand,
} from "./model";
import { rulesText } from "./preview";

const catalog = catalogJson as unknown as RulesCatalog;

/** What the engine considers equivalent: no nulls, no `params: []`, only the stop/target fields of their type. */
function normalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      if (v === null && k !== "target") continue;
      if ((k === "params" || k === "filters") && Array.isArray(v) && v.length === 0) continue;
      out[k] = normalize(v);
    }
    return out;
  }
  return value;
}

function normalizeRules(raw: unknown): unknown {
  const r = normalize(raw) as { exit?: { stop?: Record<string, unknown>; target?: Record<string, unknown> | null } };
  const keep = (o: Record<string, unknown> | null | undefined) => {
    if (!o) return o;
    const fields: Record<string, string[]> = { atr: ["type", "atr_period", "multiple"], pips: ["type", "pips"], rr: ["type", "ratio"] };
    return Object.fromEntries(Object.entries(o).filter(([k]) => (fields[String(o.type)] ?? []).includes(k)));
  };
  if (r.exit) {
    r.exit.stop = keep(r.exit.stop) ?? undefined;
    r.exit.target = keep(r.exit.target) ?? null;
  }
  return r;
}

function cond(over: Partial<ConditionState> = {}): ConditionState {
  return { ...defaultCondition(catalog), ...over };
}

function stateWith(over: Partial<BuilderState> = {}): BuilderState {
  return { ...defaultState(catalog), name: "Test", ...over };
}

describe("round trip", () => {
  it.each(templates.map((t) => [t.slug, t] as const))("stateToRules(rulesToState(%s)) equals the normalised stored rules", (_slug, t) => {
    const state = rulesToState(t.parameters as unknown as RuleSet, catalog, { name: t.name });
    const rules = stateToRules(state, catalog);
    expect(rules).toEqual(normalizeRules(t.parameters));
    // …and is stable on a second pass.
    expect(stateToRules(rulesToState(rules, catalog), catalog)).toEqual(rules);
    // …and keeps the same English.
    expect(rulesText(rules, catalog)).toBe(t.rules_text);
    expect(previewLines(state, catalog).join(" ")).toBe(t.rules_text);
    expect(findProblems(state, catalog)).toEqual([]);
  });

  it("never emits nulls except an explicit 'no target'", () => {
    for (const t of templates) {
      const json = JSON.stringify(stateToRules(rulesToState(t.parameters as unknown as RuleSet, catalog), catalog));
      expect(json).not.toContain("null");
    }
  });

  it("fills missing settings and outputs with catalogue defaults", () => {
    const rules: RuleSet = {
      schema_version: 1,
      timeframe: "M15",
      entry: { buy: { any: [{ left: { indicator: "macd" }, op: "crosses_above", right: { indicator: "macd", output: "signal" }, within_bars: 3 }] } },
    };
    const out = stateToRules(rulesToState(rules, catalog), catalog);
    expect(out).toEqual({
      schema_version: 1,
      timeframe: "M15",
      entry: {
        buy: {
          any: [
            {
              left: { indicator: "macd", params: { fast: 12, slow: 26, signal: 9 }, output: "line" },
              op: "crosses_above",
              right: { indicator: "macd", params: { fast: 12, slow: 26, signal: 9 }, output: "signal" },
              within_bars: 3,
            },
          ],
        },
      },
      // Omitted exit = the engine defaults (2 × ATR 14, 2R).
      exit: { stop: { type: "atr", atr_period: 14, multiple: 2 }, target: { type: "rr", ratio: 2 } },
    });
  });

  it("keeps filters, between, no target and pip stops", () => {
    const rules: RuleSet = {
      schema_version: 1,
      timeframe: "H1",
      entry: { sell: { all: [{ left: { indicator: "rsi", params: { period: 7 }, output: "value" }, op: "between", low: { value: 40 }, high: { value: 60 } }] } },
      filters: [{ left: { price: "close" }, op: "lt", right: { indicator: "sma", params: { period: 200, source: "close" }, output: "value" } }],
      exit: { stop: { type: "pips", pips: 25 }, target: null, close_sell_when: { any: [{ left: { price: "close" }, op: "gt", right: { indicator: "ema", params: { period: 20, source: "close" }, output: "value" } }] } },
    };
    const state = rulesToState(rules, catalog);
    expect(state.target.type).toBe("none");
    expect(state.filters).toHaveLength(1);
    expect(stateToRules(state, catalog)).toEqual(rules);
  });

  it("carries name and description", () => {
    const s = rulesToState(templates[0]!.parameters as unknown as RuleSet, catalog, { name: "A", description: "B" });
    expect([s.name, s.description]).toEqual(["A", "B"]);
  });
});

describe("defaults", () => {
  it("defaultCondition is EMA 9 crosses above EMA 21", () => {
    const c = defaultCondition(catalog);
    expect(conditionToRules(c, catalog)).toEqual({
      left: { indicator: "ema", params: { period: 9, source: "close" }, output: "value" },
      op: "crosses_above",
      right: { indicator: "ema", params: { period: 21, source: "close" }, output: "value" },
    });
  });

  it("defaultState is a valid M5 buy rule with 2 × ATR 14 and 2R", () => {
    const s = defaultState(catalog);
    expect(s.timeframe).toBe("M5");
    expect(previewLines(s, catalog)).toEqual([
      "Buy when EMA 9 crosses above EMA 21.",
      "Stop: 2 × ATR 14 from the entry; target: 2 × the stop distance (Spot and Multiplier trades).",
      "Checked on every closed M5 bar.",
    ]);
    expect(localProblems(s, catalog)).toEqual(["Give the strategy a name"]);
  });

  it("builds operands", () => {
    expect(operandToRules(priceOperand(catalog, "high"), catalog)).toEqual({ price: "high" });
    expect(operandToRules(valueOperand(catalog, 30), catalog)).toEqual({ value: 30 });
    expect(operandToRules(indicatorOperand(catalog, "bollinger", {}, "percent_b"), catalog)).toEqual({ indicator: "bollinger", params: { period: 20, stddev: 2 }, output: "percent_b" });
    expect(defaultParams(findIndicator(catalog, "highest"))).toEqual({ period: "20", source: "high" });
    expect(defaultParams(undefined)).toEqual({});
  });

  it("clones and mirrors conditions with fresh ids", () => {
    const c = defaultCondition(catalog);
    const copy = cloneCondition(c);
    expect(copy.id).not.toBe(c.id);
    copy.left.params.period = "50";
    expect(c.left.params.period).toBe("9");
    expect(mirrorCondition(c).op).toBe("crosses_below");
    expect(mirrorCondition({ ...c, op: "gte" }).op).toBe("lte");
    expect(mirrorCondition({ ...c, op: "between" }).op).toBe("between");
    expect(newId()).not.toBe(newId());
  });
});

describe("numbers and stop/target", () => {
  it("parses typed numbers", () => {
    expect(parseNumber(" 2.5 ")).toBe(2.5);
    expect(parseNumber("")).toBeNull();
    expect(parseNumber("abc")).toBeNull();
    expect(formatBound(1_000_000_000)).toBe("1,000,000,000");
    expect(formatBound(0.1)).toBe("0.1");
    expect(formatBound(100_000)).toBe("100,000");
    expect(formatBound(500)).toBe("500");
  });

  it("emits only the fields of the chosen type", () => {
    expect(stopToRules({ type: "atr", atr_period: "10", multiple: "1.5", pips: "9" })).toEqual({ type: "atr", atr_period: 10, multiple: 1.5 });
    expect(stopToRules({ type: "pips", atr_period: "10", multiple: "1.5", pips: "9" })).toEqual({ type: "pips", pips: 9 });
    const t = { ratio: "1.5", atr_period: "14", multiple: "3", pips: "30" };
    expect(targetToRules({ ...t, type: "rr" })).toEqual({ type: "rr", ratio: 1.5 });
    expect(targetToRules({ ...t, type: "atr" })).toEqual({ type: "atr", atr_period: 14, multiple: 3 });
    expect(targetToRules({ ...t, type: "pips" })).toEqual({ type: "pips", pips: 30 });
    expect(targetToRules({ ...t, type: "none" })).toBeNull();
  });

  it("omits entry sides and filters that are not there", () => {
    const rules = stateToRules(stateWith({ buy: null, sell: { mode: "any", conditions: [cond()] } }), catalog);
    expect(Object.keys(rules.entry)).toEqual(["sell"]);
    expect(rules.filters).toBeUndefined();
    expect(Object.keys(rules.exit ?? {})).toEqual(["stop", "target"]);
  });
});

describe("operand helpers", () => {
  it("computes identity and scale", () => {
    expect(operandKey(indicatorOperand(catalog, "ema", { period: 9 }), catalog)).toBe(operandKey(indicatorOperand(catalog, "ema", { period: "9.0" }), catalog));
    expect(operandScale(valueOperand(catalog, 3), catalog)).toBeNull();
    expect(operandScale(priceOperand(catalog), catalog)).toBe("price");
    expect(operandScale(indicatorOperand(catalog, "rsi"), catalog)).toBe("oscillator");
    expect(operandScale(indicatorOperand(catalog, "bollinger", {}, "percent_b"), catalog)).toBe("ratio");
    expect(scaleMeaning("oscillator", catalog)).toBe("a 0–100 oscillator");
    expect(scaleMeaning("unknown", catalog)).toBe("unknown");
  });

  it("checks indicator settings in the engine's words", () => {
    expect(operandProblems(indicatorOperand(catalog, "ema", { period: 0 }), catalog)).toEqual(["EMA period must be between 1 and 500"]);
    expect(operandProblems(indicatorOperand(catalog, "ema", { period: "2.5" }), catalog)).toEqual(["EMA period must be a whole number"]);
    expect(operandProblems(indicatorOperand(catalog, "ema", { period: "" }), catalog)).toEqual(["EMA period must be a number"]);
    expect(operandProblems(indicatorOperand(catalog, "bollinger", { stddev: 9 }), catalog)).toEqual(["Bollinger standard deviations must be between 0.1 and 5"]);
    expect(operandProblems(indicatorOperand(catalog, "macd", { fast: 26, slow: 12 }), catalog)).toEqual(["MACD fast period (26) must be smaller than the slow period (12)"]);
    expect(operandProblems(indicatorOperand(catalog, "nope"), catalog)).toEqual(["Unknown indicator nope"]);
    expect(operandProblems(valueOperand(catalog, ""), catalog)).toEqual(["Enter a number"]);
    expect(operandProblems(valueOperand(catalog, "x"), catalog)).toEqual(["This must be a number"]);
    expect(operandProblems(valueOperand(catalog, 2e9), catalog)).toEqual(["Numbers must be between −1,000,000,000 and 1,000,000,000"]);
    expect(operandProblems(priceOperand(catalog), catalog)).toEqual([]);
  });
});

describe("conditionProblems", () => {
  it("refuses numbers on both sides and numbers that cross", () => {
    expect(conditionProblems(cond({ left: valueOperand(catalog, 1), op: "gt", right: valueOperand(catalog, 2) }), catalog)).toEqual(["A condition must look at the market, not only at fixed numbers"]);
    expect(conditionProblems(cond({ left: valueOperand(catalog, 30), op: "crosses_above", right: indicatorOperand(catalog, "rsi") }), catalog)).toEqual([
      "A fixed number cannot cross anything: put it on the right-hand side",
    ]);
  });

  it("refuses comparing a thing with itself", () => {
    const e = indicatorOperand(catalog, "ema", { period: 20 });
    expect(conditionProblems(cond({ left: e, right: { ...e } }), catalog)).toEqual(["EMA 20 is compared with itself"]);
  });

  it("refuses scale mismatches", () => {
    expect(conditionProblems(cond({ left: indicatorOperand(catalog, "rsi"), right: indicatorOperand(catalog, "ema", { period: 50 }) }), catalog)).toEqual([
      "RSI 14 (a 0–100 oscillator) cannot be compared with EMA 50 (a price)",
    ]);
    expect(conditionProblems(cond({ left: indicatorOperand(catalog, "rsi"), op: "gt", right: valueOperand(catalog, 50) }), catalog)).toEqual([]);
  });

  it("checks between ranges", () => {
    const base = { left: indicatorOperand(catalog, "rsi"), op: "between" as const };
    expect(conditionProblems(cond({ ...base, low: valueOperand(catalog, 70), high: valueOperand(catalog, 30) }), catalog)).toEqual([
      "The low value of 'is between' must not be above the high value",
    ]);
    expect(conditionProblems(cond({ ...base, low: valueOperand(catalog, 30), high: valueOperand(catalog, 70) }), catalog)).toEqual([]);
  });

  it("checks within_bars", () => {
    expect(conditionProblems(cond({ withinBars: "51" }), catalog)).toEqual(["'within the last N bars' must be a whole number from 1 to 50"]);
    expect(conditionProblems(cond({ withinBars: "3" }), catalog)).toEqual([]);
    expect(conditionProblems(cond({ op: "gt", withinBars: "3" }), catalog)).toEqual(["'within the last N bars' only applies to crosses above / below"]);
  });

  it("reports operand problems with their side first", () => {
    expect(conditionProblems(cond({ right: indicatorOperand(catalog, "ema", { period: 900 }) }), catalog)).toEqual(["(right side) EMA period must be between 1 and 500"]);
  });
});

describe("findProblems / localProblems", () => {
  it("places problems where they belong", () => {
    const bad = cond({ left: indicatorOperand(catalog, "ema", { period: 0 }) });
    const s = stateWith({ buy: { mode: "all", conditions: [cond(), bad] } });
    expect(findProblems(s, catalog)).toEqual([{ at: bad.id, text: "Buy rule, condition 2 (left side): EMA period must be between 1 and 500" }]);
  });

  it("needs a name, a side and conditions", () => {
    const s = stateWith({ name: " ", buy: null, sell: null });
    expect(localProblems(s, catalog)).toEqual(["Give the strategy a name", "Add a buy rule, a sell rule, or both"]);
    const empty = stateWith({ sell: { mode: "all", conditions: [] } });
    expect(localProblems(empty, catalog)).toEqual(["Sell rule: Add at least one condition"]);
    expect(localProblems(stateWith({ name: "x".repeat(121) }), catalog)).toEqual(["The name can be at most 120 characters"]);
    expect(localProblems(stateWith({ description: "x".repeat(2001) }), catalog)).toEqual(["The description can be at most 2000 characters"]);
  });

  it("limits the total number of conditions", () => {
    const many = Array.from({ length: 13 }, () => cond());
    const s = stateWith({ buy: { mode: "any", conditions: many } });
    expect(totalConditions(s)).toBe(13);
    expect(localProblems(s, catalog)[0]).toMatch(/^A strategy can have at most 12 conditions in total \(this one has 13\)/);
  });

  it("labels filters and exit rules, and needs the matching entry side", () => {
    const f = cond({ left: valueOperand(catalog, 1), op: "gt", right: valueOperand(catalog, 2) });
    const s = stateWith({ filters: [f], closeSell: { mode: "any", conditions: [cond()] } });
    expect(localProblems(s, catalog)).toEqual(["Filter 1: A condition must look at the market, not only at fixed numbers", "There is an exit rule for sells, but no sell rule"]);
  });

  it("checks stop and target bounds", () => {
    const s = stateWith({
      stop: { type: "atr", atr_period: "0", multiple: "25", pips: "" },
      target: { type: "rr", ratio: "0", atr_period: "14", multiple: "3", pips: "" },
    });
    expect(localProblems(s, catalog)).toEqual([
      "Stop: the ATR period must be between 1 and 500",
      "Stop: the ATR multiple must be between 0.1 and 20",
      "Target: the reward/risk ratio must be between 0.1 and 20",
    ]);
    const p = stateWith({
      stop: { type: "pips", atr_period: "14", multiple: "2", pips: "0" },
      target: { type: "atr", ratio: "2", atr_period: "1.5", multiple: "60", pips: "" },
    });
    expect(localProblems(p, catalog)).toEqual([
      "Stop: the number of pips must be above 0",
      "Target: the ATR period must be a whole number",
      "Target: the ATR multiple must be between 0.1 and 50",
    ]);
    const q = stateWith({ target: { type: "pips", ratio: "2", atr_period: "14", multiple: "3", pips: "" }, stop: { type: "pips", atr_period: "", multiple: "", pips: "200000" } });
    expect(localProblems(q, catalog)).toEqual(["Stop: the number of pips must be at most 100,000", "Target: the number of pips must be a number"]);
    expect(localProblems(stateWith({ target: { type: "none", ratio: "", atr_period: "", multiple: "", pips: "" } }), catalog)).toEqual([]);
  });
});
