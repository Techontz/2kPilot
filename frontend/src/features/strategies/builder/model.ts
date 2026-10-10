/**
 * Visual strategy builder — pure state model (no React).
 *
 * The builder edits a `BuilderState` (strings for every number field so the
 * inputs can hold half-typed values) and converts it to / from the engine's
 * rule-set format (schema_version 1, see docs/STRATEGIES.md and
 * trading-engine/src/fxrobot/strategy_engine/rules/model.py).
 *
 * - `rulesToState` accepts what the API stores: explicit nulls, `params: []`
 *   (an empty PHP array), omitted params/outputs (catalogue defaults).
 * - `stateToRules` produces a clean rule set: no nulls, only the fields that
 *   apply, `filters` only when non-empty, `exit.target: null` for "no target".
 * - `findProblems` mirrors the engine's cheap checks with the engine's wording;
 *   the API remains the authority.
 */
import type {
  CatalogIndicator,
  Condition,
  ConditionGroup,
  Operand,
  OperatorKey,
  PriceField,
  RuleSet,
  RulesCatalog,
  StopRule,
  TargetRule,
  Timeframe,
} from "@/lib/types";
import { operandLabel, ruleLines } from "./preview";

// ── State ────────────────────────────────────────────────────────────────

export type OperandKind = "price" | "value" | "indicator";

export interface OperandState {
  kind: OperandKind;
  price: PriceField;
  /** The number as typed. */
  value: string;
  indicator: string;
  /** Indicator settings as typed (numbers) or chosen (price sources). */
  params: Record<string, string>;
  output: string;
}

export interface ConditionState {
  id: string;
  left: OperandState;
  op: OperatorKey;
  right: OperandState;
  low: OperandState;
  high: OperandState;
  /** "" = not set (crosses only). */
  withinBars: string;
}

export type GroupMode = "all" | "any";

export interface GroupState {
  mode: GroupMode;
  conditions: ConditionState[];
}

export interface StopState {
  type: StopRule["type"];
  atr_period: string;
  multiple: string;
  pips: string;
}

export interface TargetState {
  type: TargetRule["type"] | "none";
  ratio: string;
  atr_period: string;
  multiple: string;
  pips: string;
}

export interface BuilderState {
  name: string;
  description: string;
  timeframe: Timeframe;
  buy: GroupState | null;
  sell: GroupState | null;
  filters: ConditionState[];
  stop: StopState;
  target: TargetState;
  closeBuy: GroupState | null;
  closeSell: GroupState | null;
}

export type GroupKey = "buy" | "sell" | "closeBuy" | "closeSell";

export const GROUP_KEYS: GroupKey[] = ["buy", "sell", "closeBuy", "closeSell"];

/** The engine's names for each place (used in problem messages). */
export const PLACE_NAMES: Record<GroupKey, string> = {
  buy: "Buy rule",
  sell: "Sell rule",
  closeBuy: "Exit rule for buys",
  closeSell: "Exit rule for sells",
};

export const NAME_MAX = 120;
export const DESCRIPTION_MAX = 2000;

export const STOP_BOUNDS = {
  atr_period: { min: 1, max: 500, integer: true },
  multiple: { min: 0.1, max: 20, integer: false },
  pips: { min: 0, max: 100_000, integer: false, exclusiveMin: true },
} as const;

export const TARGET_BOUNDS = {
  ratio: { min: 0.1, max: 20, integer: false },
  atr_period: { min: 1, max: 500, integer: true },
  multiple: { min: 0.1, max: 50, integer: false },
  pips: { min: 0, max: 100_000, integer: false, exclusiveMin: true },
} as const;

const PRICE_FIELDS: PriceField[] = ["open", "high", "low", "close"];

let idCounter = 0;
/** A unique id for a condition row (React key / problem anchor). */
export function newId(): string {
  idCounter += 1;
  return `c${idCounter}-${Math.random().toString(36).slice(2, 7)}`;
}

// ── Catalogue helpers ───────────────────────────────────────────────────

export function findIndicator(catalog: RulesCatalog, key: string): CatalogIndicator | undefined {
  return catalog.indicators.find((i) => i.key === key);
}

/** Indicator settings at their catalogue defaults, as strings. */
export function defaultParams(indicator: CatalogIndicator | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of indicator?.params ?? []) out[p.key] = String(p.default);
  return out;
}

function str(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

// ── Defaults ────────────────────────────────────────────────────────────

export function indicatorOperand(catalog: RulesCatalog, key: string, params: Record<string, string | number> = {}, output?: string): OperandState {
  const spec = findIndicator(catalog, key);
  const merged = defaultParams(spec);
  for (const [k, v] of Object.entries(params)) merged[k] = String(v);
  return {
    kind: "indicator",
    price: "close",
    value: "",
    indicator: key,
    params: merged,
    output: output ?? spec?.default_output ?? "value",
  };
}

export function priceOperand(catalog: RulesCatalog, price: PriceField = "close"): OperandState {
  return { ...indicatorOperand(catalog, firstIndicatorKey(catalog)), kind: "price", price };
}

export function valueOperand(catalog: RulesCatalog, value: number | string = ""): OperandState {
  return { ...indicatorOperand(catalog, firstIndicatorKey(catalog)), kind: "value", value: String(value) };
}

function firstIndicatorKey(catalog: RulesCatalog): string {
  return findIndicator(catalog, "ema") ? "ema" : (catalog.indicators[0]?.key ?? "ema");
}

/** "EMA 9 crosses above EMA 21" — a sensible first condition. */
export function defaultCondition(catalog: RulesCatalog): ConditionState {
  return {
    id: newId(),
    left: indicatorOperand(catalog, "ema", { period: 9 }),
    op: "crosses_above",
    right: indicatorOperand(catalog, "ema", { period: 21 }),
    low: valueOperand(catalog, 30),
    high: valueOperand(catalog, 70),
    withinBars: "",
  };
}

export function defaultStop(): StopState {
  return { type: "atr", atr_period: "14", multiple: "2", pips: "" };
}

export function defaultTarget(): TargetState {
  return { type: "rr", ratio: "2", atr_period: "14", multiple: "3", pips: "" };
}

export function defaultGroup(catalog: RulesCatalog): GroupState {
  return { mode: "all", conditions: [defaultCondition(catalog)] };
}

/** A new strategy: M5, buy when EMA 9 crosses above EMA 21, 2 × ATR 14 stop, 2R target. */
export function defaultState(catalog: RulesCatalog): BuilderState {
  return {
    name: "",
    description: "",
    timeframe: catalog.timeframes.includes("M5") ? "M5" : (catalog.timeframes[0] ?? "M5"),
    buy: defaultGroup(catalog),
    sell: null,
    filters: [],
    stop: defaultStop(),
    target: defaultTarget(),
    closeBuy: null,
    closeSell: null,
  };
}

/** The mirror image of a condition (for "add a sell rule like the buy rule"). */
export function mirrorCondition(c: ConditionState): ConditionState {
  const flip: Partial<Record<OperatorKey, OperatorKey>> = {
    crosses_above: "crosses_below",
    crosses_below: "crosses_above",
    gt: "lt",
    lt: "gt",
    gte: "lte",
    lte: "gte",
  };
  return { ...cloneCondition(c), op: flip[c.op] ?? c.op };
}

export function cloneCondition(c: ConditionState): ConditionState {
  const op = (o: OperandState): OperandState => ({ ...o, params: { ...o.params } });
  return { ...c, id: newId(), left: op(c.left), right: op(c.right), low: op(c.low), high: op(c.high) };
}

// ── Rules → state ───────────────────────────────────────────────────────

function operandToState(raw: Operand | null | undefined, catalog: RulesCatalog, fallback: OperandState): OperandState {
  if (!raw) return { ...fallback, params: { ...fallback.params } };
  if (raw.indicator !== null && raw.indicator !== undefined) {
    const params = raw.params && !Array.isArray(raw.params) ? raw.params : {};
    return indicatorOperand(catalog, raw.indicator, params, raw.output ?? undefined);
  }
  if (raw.price !== null && raw.price !== undefined) return { ...fallback, params: { ...fallback.params }, kind: "price", price: raw.price };
  return { ...fallback, params: { ...fallback.params }, kind: "value", value: str(raw.value) };
}

function conditionToState(raw: Condition, catalog: RulesCatalog): ConditionState {
  const base = defaultCondition(catalog);
  const isBetween = raw.op === "between";
  return {
    id: newId(),
    left: operandToState(raw.left, catalog, base.left),
    op: raw.op,
    right: operandToState(isBetween ? null : raw.right, catalog, isBetween ? base.right : base.right),
    low: operandToState(isBetween ? raw.low : null, catalog, base.low),
    high: operandToState(isBetween ? raw.high : null, catalog, base.high),
    withinBars: str(raw.within_bars),
  };
}

function groupToState(raw: ConditionGroup | null | undefined, catalog: RulesCatalog): GroupState | null {
  if (!raw) return null;
  const mode: GroupMode = raw.all !== null && raw.all !== undefined ? "all" : "any";
  const list = (mode === "all" ? raw.all : raw.any) ?? [];
  return { mode, conditions: list.map((c) => conditionToState(c, catalog)) };
}

export function rulesToState(rules: RuleSet, catalog: RulesCatalog, meta: { name?: string | null; description?: string | null } = {}): BuilderState {
  const exit = rules.exit ?? {};
  const stop = exit.stop;
  const target = exit.target;
  const ds = defaultStop();
  const dt = defaultTarget();
  return {
    name: meta.name ?? "",
    description: meta.description ?? "",
    timeframe: rules.timeframe ?? "M5",
    buy: groupToState(rules.entry?.buy, catalog),
    sell: groupToState(rules.entry?.sell, catalog),
    filters: (rules.filters ?? []).map((c) => conditionToState(c, catalog)),
    stop: stop
      ? {
          type: stop.type ?? "atr",
          atr_period: stop.atr_period === null || stop.atr_period === undefined ? ds.atr_period : str(stop.atr_period),
          multiple: stop.multiple === null || stop.multiple === undefined ? ds.multiple : str(stop.multiple),
          pips: str(stop.pips),
        }
      : ds,
    target:
      target === null
        ? { ...dt, type: "none" }
        : target === undefined
          ? dt
          : {
              type: target.type ?? "rr",
              ratio: target.ratio === null || target.ratio === undefined ? dt.ratio : str(target.ratio),
              atr_period: target.atr_period === null || target.atr_period === undefined ? dt.atr_period : str(target.atr_period),
              multiple: target.multiple === null || target.multiple === undefined ? dt.multiple : str(target.multiple),
              pips: str(target.pips),
            },
    closeBuy: groupToState(exit.close_buy_when, catalog),
    closeSell: groupToState(exit.close_sell_when, catalog),
  };
}

// ── State → rules ───────────────────────────────────────────────────────

/**
 * A typed number as a number. Anything that isn't a finite number is passed
 * through as text so the engine's own message explains it (the builder blocks
 * saving on local problems first, so this only matters for previews).
 */
export function parseNumber(text: string): number | null {
  const t = text.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function num(text: string): number {
  const n = parseNumber(text);
  return (n ?? text.trim()) as number;
}

export function operandToRules(o: OperandState, catalog: RulesCatalog): Operand {
  if (o.kind === "price") return { price: o.price };
  if (o.kind === "value") return { value: num(o.value) };
  const spec = findIndicator(catalog, o.indicator);
  const params: Record<string, number | string> = {};
  const keys = spec ? spec.params.map((p) => p.key) : Object.keys(o.params);
  for (const key of keys) {
    const p = spec?.params.find((x) => x.key === key);
    const raw = o.params[key] ?? (p ? String(p.default) : "");
    params[key] = p?.type === "source" ? raw : num(raw);
  }
  const out: Operand = { indicator: o.indicator, params };
  out.output = o.output || spec?.default_output || "value";
  return out;
}

export function conditionToRules(c: ConditionState, catalog: RulesCatalog): Condition {
  const left = operandToRules(c.left, catalog);
  if (c.op === "between") return { left, op: c.op, low: operandToRules(c.low, catalog), high: operandToRules(c.high, catalog) };
  const out: Condition = { left, op: c.op, right: operandToRules(c.right, catalog) };
  if (isCross(c.op) && c.withinBars.trim() !== "") out.within_bars = num(c.withinBars);
  return out;
}

function groupToRules(g: GroupState, catalog: RulesCatalog): ConditionGroup {
  const list = g.conditions.map((c) => conditionToRules(c, catalog));
  return g.mode === "all" ? { all: list } : { any: list };
}

export function stopToRules(s: StopState): StopRule {
  return s.type === "pips" ? { type: "pips", pips: num(s.pips) } : { type: "atr", atr_period: num(s.atr_period), multiple: num(s.multiple) };
}

export function targetToRules(t: TargetState): TargetRule | null {
  switch (t.type) {
    case "none":
      return null;
    case "pips":
      return { type: "pips", pips: num(t.pips) };
    case "atr":
      return { type: "atr", atr_period: num(t.atr_period), multiple: num(t.multiple) };
    default:
      return { type: "rr", ratio: num(t.ratio) };
  }
}

export function stateToRules(state: BuilderState, catalog: RulesCatalog): RuleSet {
  const entry: RuleSet["entry"] = {};
  if (state.buy) entry.buy = groupToRules(state.buy, catalog);
  if (state.sell) entry.sell = groupToRules(state.sell, catalog);
  const exit: NonNullable<RuleSet["exit"]> = { stop: stopToRules(state.stop), target: targetToRules(state.target) };
  if (state.closeBuy) exit.close_buy_when = groupToRules(state.closeBuy, catalog);
  if (state.closeSell) exit.close_sell_when = groupToRules(state.closeSell, catalog);
  const rules: RuleSet = { schema_version: 1, timeframe: state.timeframe, entry };
  if (state.filters.length > 0) rules.filters = state.filters.map((c) => conditionToRules(c, catalog));
  rules.exit = exit;
  return rules;
}

// ── Local problems ──────────────────────────────────────────────────────

/**
 * Where a problem belongs: "name", "description", "entry", "total", "stop",
 * "target", a group key ("buy"…) for group-level problems, or the condition id.
 */
export interface Problem {
  at: string;
  text: string;
}

export function isCross(op: OperatorKey): boolean {
  return op === "crosses_above" || op === "crosses_below";
}

export function formatBound(n: number): string {
  return Math.abs(n) >= 10_000 ? Math.round(n).toLocaleString("en-US") : String(n);
}

/** Problems with one operand, in the engine's words ("EMA period must be between 1 and 500"). */
export function operandProblems(o: OperandState, catalog: RulesCatalog): string[] {
  if (o.kind === "price") return PRICE_FIELDS.includes(o.price) ? [] : ["Choose a price: open, high, low or close"];
  if (o.kind === "value") {
    const n = parseNumber(o.value);
    if (n === null) return [o.value.trim() === "" ? "Enter a number" : "This must be a number"];
    const max = catalog.limits.max_constant;
    if (Math.abs(n) > max) return [`Numbers must be between −${formatBound(max)} and ${formatBound(max)}`];
    return [];
  }
  const spec = findIndicator(catalog, o.indicator);
  if (!spec) return [`Unknown indicator ${o.indicator || "(none)"}`];
  const out: string[] = [];
  const clean: Record<string, number> = {};
  for (const p of spec.params) {
    const raw = o.params[p.key] ?? String(p.default);
    if (p.type === "source") {
      if (!PRICE_FIELDS.includes(raw as PriceField)) out.push(`${spec.short} price must be one of open, high, low, close`);
      continue;
    }
    const label = p.label.toLowerCase();
    const n = parseNumber(raw);
    if (n === null) {
      out.push(`${spec.short} ${label} must be a number`);
      continue;
    }
    if (p.type === "integer" && !Number.isInteger(n)) {
      out.push(`${spec.short} ${label} must be a whole number`);
      continue;
    }
    if ((p.min !== null && p.min !== undefined && n < p.min) || (p.max !== null && p.max !== undefined && n > p.max)) {
      out.push(`${spec.short} ${label} must be between ${formatBound(p.min ?? 0)} and ${formatBound(p.max ?? 0)}`);
      continue;
    }
    clean[p.key] = n;
  }
  if (spec.key === "macd" && out.length === 0 && clean.fast !== undefined && clean.slow !== undefined && clean.fast >= clean.slow) {
    out.push(`MACD fast period (${clean.fast}) must be smaller than the slow period (${clean.slow})`);
  }
  if (!spec.outputs.some((x) => x.key === (o.output || spec.default_output))) {
    out.push(`${spec.short} has no output '${o.output}' (choose: ${spec.outputs.map((x) => x.key).join(", ")})`);
  }
  return out;
}

/** Identity of an operand, as the engine computes it (to spot "compared with itself"). */
export function operandKey(o: OperandState, catalog: RulesCatalog): string {
  if (o.kind === "price") return `price:${o.price}`;
  if (o.kind === "value") return `value:${parseNumber(o.value)}`;
  const spec = findIndicator(catalog, o.indicator);
  const params = (spec?.params ?? [])
    .map((p) => {
      const raw = o.params[p.key] ?? String(p.default);
      return `${p.key}=${p.type === "source" ? raw : parseNumber(raw)}`;
    })
    .sort()
    .join(",");
  return `${o.indicator}(${params}).${o.output || spec?.default_output}`;
}

/** What an operand's numbers mean; null for a plain number (comparable with anything). */
export function operandScale(o: OperandState, catalog: RulesCatalog): string | null {
  if (o.kind === "value") return null;
  if (o.kind === "price") return "price";
  const spec = findIndicator(catalog, o.indicator);
  return spec?.outputs.find((x) => x.key === (o.output || spec.default_output))?.scale ?? null;
}

const FALLBACK_SCALE_MEANING: Record<string, string> = {
  price: "a price",
  oscillator: "a 0–100 oscillator",
  ratio: "a band position (0 = lower band, 1 = upper band)",
  macd: "a MACD value (difference of two averages, around 0)",
  price_distance: "a price distance (volatility)",
  percent: "a percentage change",
};

export function scaleMeaning(scale: string, catalog: RulesCatalog): string {
  for (const i of catalog.indicators) {
    const o = i.outputs.find((x) => x.scale === scale);
    if (o?.meaning) return o.meaning;
  }
  return FALLBACK_SCALE_MEANING[scale] ?? scale;
}

/** Problems with one condition (operands first, like the engine). */
export function conditionProblems(c: ConditionState, catalog: RulesCatalog): string[] {
  const label = (o: OperandState) => operandLabel(operandToRules(o, catalog), catalog);
  const sides: [string, OperandState][] =
    c.op === "between"
      ? [
          ["left", c.left],
          ["low", c.low],
          ["high", c.high],
        ]
      : [
          ["left", c.left],
          ["right", c.right],
        ];
  const out: string[] = [];
  for (const [side, o] of sides) {
    for (const p of operandProblems(o, catalog)) out.push(`(${side} side) ${p}`);
  }
  if (c.withinBars.trim() !== "") {
    const n = parseNumber(c.withinBars);
    const max = catalog.limits.max_within_bars;
    if (!isCross(c.op)) out.push("'within the last N bars' only applies to crosses above / below");
    else if (n === null || !Number.isInteger(n) || n < 1 || n > max) out.push(`'within the last N bars' must be a whole number from 1 to ${max}`);
  }
  if (out.length > 0) return out;
  const others = c.op === "between" ? [c.low, c.high] : [c.right];
  if (c.left.kind === "value" && others.every((o) => o.kind === "value")) {
    return ["A condition must look at the market, not only at fixed numbers"];
  }
  if (c.left.kind === "value" && isCross(c.op)) return ["A fixed number cannot cross anything: put it on the right-hand side"];
  const leftKey = operandKey(c.left, catalog);
  for (const other of others) {
    if (operandKey(other, catalog) === leftKey) return [`${label(c.left)} is compared with itself`];
    const a = operandScale(c.left, catalog);
    const b = operandScale(other, catalog);
    if (a !== null && b !== null && a !== b) {
      return [`${label(c.left)} (${scaleMeaning(a, catalog)}) cannot be compared with ${label(other)} (${scaleMeaning(b, catalog)})`];
    }
  }
  if (c.op === "between" && c.low.kind === "value" && c.high.kind === "value") {
    const lo = parseNumber(c.low.value);
    const hi = parseNumber(c.high.value);
    if (lo !== null && hi !== null && lo > hi) return ["The low value of 'is between' must not be above the high value"];
  }
  return out;
}

function boundProblem(what: string, text: string, b: { min: number; max: number; integer: boolean; exclusiveMin?: boolean }): string | null {
  const n = parseNumber(text);
  if (n === null) return `${what} must be a number`;
  if (b.integer && !Number.isInteger(n)) return `${what} must be a whole number`;
  if (b.exclusiveMin ? n <= b.min : n < b.min) {
    return b.exclusiveMin ? `${what} must be above ${b.min}` : `${what} must be between ${b.min} and ${formatBound(b.max)}`;
  }
  if (n > b.max) return b.exclusiveMin ? `${what} must be at most ${formatBound(b.max)}` : `${what} must be between ${b.min} and ${formatBound(b.max)}`;
  return null;
}

export function totalConditions(state: BuilderState): number {
  return GROUP_KEYS.reduce((sum, k) => sum + (state[k]?.conditions.length ?? 0), 0) + state.filters.length;
}

/**
 * Client-side checks mirroring the engine's validator. Each problem says where
 * it belongs (`at`) so the UI can show it next to the offending row.
 */
export function findProblems(state: BuilderState, catalog: RulesCatalog): Problem[] {
  const out: Problem[] = [];
  const name = state.name.trim();
  if (name === "") out.push({ at: "name", text: "Give the strategy a name" });
  else if (name.length > NAME_MAX) out.push({ at: "name", text: `The name can be at most ${NAME_MAX} characters` });
  if (state.description.length > DESCRIPTION_MAX) out.push({ at: "description", text: `The description can be at most ${DESCRIPTION_MAX} characters` });

  if (!state.buy && !state.sell) out.push({ at: "entry", text: "Add a buy rule, a sell rule, or both" });
  const total = totalConditions(state);
  const max = catalog.limits.max_conditions;
  if (total > max) {
    out.push({
      at: "total",
      text: `A strategy can have at most ${max} conditions in total (this one has ${total}) — simpler rules are easier to trust and less likely to be overfitted`,
    });
  }
  for (const key of GROUP_KEYS) {
    const g = state[key];
    if (!g) continue;
    if (g.conditions.length === 0) out.push({ at: key, text: `${PLACE_NAMES[key]}: Add at least one condition` });
    g.conditions.forEach((c, i) => {
      for (const p of conditionProblems(c, catalog)) out.push({ at: c.id, text: joinWhere(`${PLACE_NAMES[key]}, condition ${i + 1}`, p) });
    });
  }
  state.filters.forEach((c, i) => {
    for (const p of conditionProblems(c, catalog)) out.push({ at: c.id, text: joinWhere(`Filter ${i + 1}`, p) });
  });
  if (state.closeBuy && !state.buy) out.push({ at: "closeBuy", text: "There is an exit rule for buys, but no buy rule" });
  if (state.closeSell && !state.sell) out.push({ at: "closeSell", text: "There is an exit rule for sells, but no sell rule" });

  const s = state.stop;
  const stopChecks: (string | null)[] =
    s.type === "pips"
      ? [boundProblem("Stop: the number of pips", s.pips, STOP_BOUNDS.pips)]
      : [boundProblem("Stop: the ATR period", s.atr_period, STOP_BOUNDS.atr_period), boundProblem("Stop: the ATR multiple", s.multiple, STOP_BOUNDS.multiple)];
  for (const p of stopChecks) if (p) out.push({ at: "stop", text: p });

  const t = state.target;
  const targetChecks: (string | null)[] =
    t.type === "none"
      ? []
      : t.type === "pips"
        ? [boundProblem("Target: the number of pips", t.pips, TARGET_BOUNDS.pips)]
        : t.type === "atr"
          ? [boundProblem("Target: the ATR period", t.atr_period, TARGET_BOUNDS.atr_period), boundProblem("Target: the ATR multiple", t.multiple, TARGET_BOUNDS.multiple)]
          : [boundProblem("Target: the reward/risk ratio", t.ratio, TARGET_BOUNDS.ratio)];
  for (const p of targetChecks) if (p) out.push({ at: "target", text: p });
  return out;
}

function joinWhere(where: string, problem: string): string {
  // "(left side) EMA period …" → "Buy rule, condition 1 (left side): EMA period …"
  const m = /^\((\w+) side\) (.*)$/.exec(problem);
  return m ? `${where} (${m[1]} side): ${m[2]}` : `${where}: ${problem}`;
}

/** Problems as plain strings (for summaries). */
export function localProblems(state: BuilderState, catalog: RulesCatalog): string[] {
  return findProblems(state, catalog).map((p) => p.text);
}

/** The live plain-English preview of what is being built (the engine's sentences). */
export function previewLines(state: BuilderState, catalog: RulesCatalog): string[] {
  return ruleLines(stateToRules(state, catalog), catalog);
}
