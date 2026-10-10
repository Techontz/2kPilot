/**
 * Plain-English rule text — a faithful port of the engine's `Operand.label()`,
 * `Condition.to_text()`, `Group.to_text()` and `RuleSet.to_lines()`
 * (trading-engine/src/fxrobot/strategy_engine/rules/model.py), so the live
 * preview reads exactly like the `rules_text` stored with every version.
 *
 * Works on rule sets as stored (explicit nulls, `params: []`) as well as clean
 * ones; omitted settings take the catalogue defaults, like the engine.
 */
import type { Condition, ConditionGroup, ContractFamily, Operand, RuleSet, RulesCatalog, StopRule, TargetRule } from "@/lib/types";

/** Python's `f"{value:g}"` (6 significant digits), or `{:,.0f}` from a million up. */
export function fmtNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  if (Math.abs(value) >= 1e6) return Math.round(value).toLocaleString("en-US");
  if (value === 0) return Object.is(value, -0) ? "-0" : "0";
  const [mantissa = "", expText = "0"] = value.toExponential(5).split("e");
  const exp = Number(expText);
  if (exp < -4 || exp >= 6) {
    const m = mantissa.includes(".") ? mantissa.replace(/0+$/, "").replace(/\.$/, "") : mantissa;
    const sign = exp < 0 ? "-" : "+";
    return `${m}e${sign}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  const fixed = value.toFixed(Math.max(0, 5 - exp));
  return fixed.includes(".") ? fixed.replace(/0+$/, "").replace(/\.$/, "") : fixed;
}

/** A setting as Python's `str()` would print it (ints plainly; typed text as-is). */
function setting(v: number | string | undefined | null): string {
  if (v === undefined || v === null || v === "") return "…";
  return String(v);
}

function numberText(v: number | string | undefined | null): string {
  if (v === undefined || v === null || v === "") return "…";
  if (typeof v === "number") return fmtNumber(v);
  const n = Number(v);
  return v.trim() !== "" && Number.isFinite(n) ? fmtNumber(n) : v;
}

/** Settings with catalogue defaults filled in (the engine does the same). */
function filledParams(o: Operand, catalog?: RulesCatalog): Record<string, number | string> {
  const given = o.params && !Array.isArray(o.params) ? o.params : {};
  const spec = catalog?.indicators.find((i) => i.key === o.indicator);
  const out: Record<string, number | string> = {};
  for (const p of spec?.params ?? []) out[p.key] = p.default;
  for (const [k, v] of Object.entries(given)) if (v !== null && v !== undefined) out[k] = v;
  return out;
}

const MACD_NAMES: Record<string, string> = {
  line: "MACD line",
  signal: "MACD signal line",
  histogram: "MACD histogram",
};

const BOLLINGER_NAMES: Record<string, string> = {
  upper: "the upper Bollinger band",
  middle: "the middle Bollinger band",
  lower: "the lower Bollinger band",
  percent_b: "Bollinger %B",
};

/** "EMA 20", "the close", "30", "the highest high of the previous 20 bars", "Bollinger %B (20, 2)". */
export function operandLabel(o: Operand, catalog?: RulesCatalog): string {
  if (o.price !== null && o.price !== undefined) return `the ${o.price}`;
  if (o.indicator === null || o.indicator === undefined) return numberText(o.value);
  const p = filledParams(o, catalog);
  const spec = catalog?.indicators.find((i) => i.key === o.indicator);
  const output = o.output ?? spec?.default_output;
  switch (o.indicator) {
    case "sma":
    case "ema": {
      const source = p.source ?? "close";
      const src = source === "close" ? "" : ` of ${setting(source)}`;
      return `${o.indicator.toUpperCase()} ${setting(p.period)}${src}`;
    }
    case "rsi":
    case "atr":
    case "roc":
      return `${o.indicator.toUpperCase()} ${setting(p.period)}`;
    case "macd":
      return `${MACD_NAMES[output ?? "line"] ?? MACD_NAMES.line} (${setting(p.fast)}, ${setting(p.slow)}, ${setting(p.signal)})`;
    case "bollinger":
      return `${BOLLINGER_NAMES[output ?? "upper"] ?? BOLLINGER_NAMES.upper} (${setting(p.period)}, ${numberText(p.stddev)})`;
    case "highest":
    case "lowest":
      return `the ${o.indicator} ${setting(p.source)} of the previous ${setting(p.period)} bars`;
    default: {
      // Not in this build's vocabulary: a readable fallback.
      const values = Object.values(p).map((v) => setting(v));
      return `${spec?.short ?? o.indicator}${values.length ? ` ${values.join(", ")}` : ""}`;
    }
  }
}

function operatorLabel(op: string, catalog?: RulesCatalog): string {
  const fallback: Record<string, string> = {
    crosses_above: "crosses above",
    crosses_below: "crosses below",
    gt: "is above",
    gte: "is at or above",
    lt: "is below",
    lte: "is at or below",
    between: "is between",
  };
  return catalog?.operators.find((o) => o.key === op)?.label ?? fallback[op] ?? op;
}

/** "EMA 9 crosses above EMA 21 within the last 3 bars", "RSI 14 is between 30 and 70". */
export function conditionText(c: Condition, catalog?: RulesCatalog): string {
  if (c.op === "between") {
    return `${operandLabel(c.left, catalog)} is between ${c.low ? operandLabel(c.low, catalog) : "…"} and ${c.high ? operandLabel(c.high, catalog) : "…"}`;
  }
  let text = `${operandLabel(c.left, catalog)} ${operatorLabel(c.op, catalog)} ${c.right ? operandLabel(c.right, catalog) : "…"}`;
  const within = typeof c.within_bars === "number" ? c.within_bars : c.within_bars ? Number(c.within_bars) : null;
  if (within !== null && Number.isFinite(within) && within > 1) text += ` within the last ${within} bars`;
  return text;
}

/** Conditions joined with "and" / "or" — Oxford comma only for "all" groups of 3+. */
export function groupText(g: ConditionGroup, catalog?: RulesCatalog): string {
  const isAll = g.all !== null && g.all !== undefined;
  const parts = ((isAll ? g.all : g.any) ?? []).map((c) => conditionText(c, catalog));
  const joiner = isAll ? " and " : " or ";
  if (parts.length > 2) return `${parts.slice(0, -1).join(", ")}${isAll ? "," : ""}${joiner}${parts[parts.length - 1]}`;
  return parts.join(joiner);
}

export function stopText(stop: StopRule | undefined | null): string {
  const s = stop ?? { type: "atr" };
  if (s.type === "pips") return `${numberText(s.pips ?? 0)} pips`;
  return `${numberText(s.multiple ?? 2)} × ATR ${setting(s.atr_period ?? 14)}`;
}

export function targetText(target: TargetRule): string {
  if (target.type === "pips") return `${numberText(target.pips ?? 0)} pips`;
  if (target.type === "atr") return `${numberText(target.multiple ?? 3)} × ATR ${setting(target.atr_period ?? 14)}`;
  return `${numberText(target.ratio ?? 2)} × the stop distance`;
}

/** The engine's `RuleSet.to_lines()`: one sentence per part. */
export function ruleLines(rules: RuleSet, catalog?: RulesCatalog): string[] {
  const lines: string[] = [];
  const exit = rules.exit ?? {};
  if (rules.entry?.buy) lines.push(`Buy when ${groupText(rules.entry.buy, catalog)}.`);
  if (rules.entry?.sell) lines.push(`Sell when ${groupText(rules.entry.sell, catalog)}.`);
  if (rules.filters && rules.filters.length > 0) lines.push(`Only trade when ${rules.filters.map((c) => conditionText(c, catalog)).join(" and ")}.`);
  if (exit.close_buy_when) lines.push(`Close a buy early when ${groupText(exit.close_buy_when, catalog)}.`);
  if (exit.close_sell_when) lines.push(`Close a sell early when ${groupText(exit.close_sell_when, catalog)}.`);
  // An omitted target is the engine's default (2R); an explicit null is "no target".
  const target = exit.target === undefined ? ({ type: "rr", ratio: 2 } as TargetRule) : exit.target;
  const targetPart = target ? `; target: ${targetText(target)}` : "; no target";
  lines.push(`Stop: ${stopText(exit.stop)} from the entry${targetPart} (Spot and Multiplier trades).`);
  lines.push(`Checked on every closed ${rules.timeframe ?? "M5"} bar.`);
  return lines;
}

/** The whole summary on one line (the engine's `to_text()`). */
export function rulesText(rules: RuleSet, catalog?: RulesCatalog): string {
  return ruleLines(rules, catalog).join(" ");
}

const CONTRACT_EXIT_FALLBACK: Record<ContractFamily, string> = {
  RISE_FALL: "Rise/Fall contracts always run to expiry: exit conditions, stops and targets do not apply. The stake is the most you can lose.",
  MULTIPLIER: "Exit conditions close the contract early. Stops and targets become money amounts unless the assignment sets its own.",
  SPOT: "Paper only. Every trade has the stop below; exit conditions can close it earlier.",
};

/** How exits work for a contract family (the catalogue's `contract_notes`, with a built-in fallback). */
export function contractExitText(family: ContractFamily, catalog?: RulesCatalog): string {
  return catalog?.contract_notes?.[family] ?? CONTRACT_EXIT_FALLBACK[family];
}
