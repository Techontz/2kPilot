/**
 * What the Strategies page shows about a code strategy (e.g. Adaptive Trend &
 * Momentum): where it may run, its parameters and risk caps, the market regime
 * of its latest evaluation and the honest backtest verdict. Pure functions.
 */

import { FAMILY_LABEL } from "@/lib/contracts";
import type { ContractFamily, Evaluation, JsonSchemaProperty, Strategy, ValidationGate } from "@/lib/types";
import { latestVersion } from "./strategyUtils";

export const REGIMES = ["TREND_UP", "TREND_DOWN", "SIDEWAYS", "HIGH_VOLATILITY", "UNCERTAIN"] as const;
export type Regime = (typeof REGIMES)[number];

export const REGIME_LABEL: Record<Regime, string> = {
  TREND_UP: "Uptrend",
  TREND_DOWN: "Downtrend",
  SIDEWAYS: "Sideways",
  HIGH_VOLATILITY: "High volatility",
  UNCERTAIN: "Unclear",
};

export const REGIME_TONE: Record<Regime, "positive" | "negative" | "neutral" | "warning"> = {
  TREND_UP: "positive",
  TREND_DOWN: "negative",
  SIDEWAYS: "neutral",
  HIGH_VOLATILITY: "warning",
  UNCERTAIN: "neutral",
};

const ALL_FAMILIES: ContractFamily[] = ["RISE_FALL", "MULTIPLIER", "SPOT"];

/** Contract families the strategy may trade (null = any). */
export function allowedFamilies(s: Strategy): ContractFamily[] | null {
  return s.contract_families ?? s.details?.supported_contract_families ?? null;
}

/** Markets the strategy is enabled on (null = any). */
export function allowedSymbols(s: Strategy): string[] | null {
  return s.symbols ?? s.details?.supported_symbols ?? null;
}

/** What a broker offers, narrowed to what the strategy supports. */
export function familiesFor(s: Strategy, offered: ContractFamily[]): ContractFamily[] {
  const allowed = allowedFamilies(s);
  return allowed ? offered.filter((f) => allowed.includes(f)) : offered;
}

/** "Multiplier (Deriv) · Spot (Paper) · not Rise/Fall", or "Every contract type". */
export function contractSupportText(families: ContractFamily[] | null): string {
  if (!families) return "Every contract type";
  const where: Record<ContractFamily, string> = { MULTIPLIER: " (Deriv)", SPOT: " (Paper)", RISE_FALL: "" };
  const yes = ALL_FAMILIES.filter((f) => families.includes(f)).map((f) => `${FAMILY_LABEL[f]}${where[f]}`);
  const no = ALL_FAMILIES.filter((f) => !families.includes(f)).map((f) => `not ${FAMILY_LABEL[f]}`);
  return [...yes, ...no].join(" · ");
}

/** The market regime recorded in an evaluation's "Market regime" check, if any. */
export function regimeOf(e: Evaluation | null | undefined): { regime: Regime; reason: string } | null {
  const check = e?.checks.find((c) => c.name === "Market regime");
  const fromCheck = check?.detail.match(/^(TREND_UP|TREND_DOWN|SIDEWAYS|HIGH_VOLATILITY|UNCERTAIN)\s*—\s*(.*)$/);
  if (fromCheck) return { regime: fromCheck[1] as Regime, reason: fromCheck[2] ?? "" };
  // A regime refusal ("No trade: regime SIDEWAYS — …") carries it in the summary.
  const fromSummary = e?.summary.match(/regime (TREND_UP|TREND_DOWN|SIDEWAYS|HIGH_VOLATILITY|UNCERTAIN)\s*—\s*(.*)$/);
  return fromSummary ? { regime: fromSummary[1] as Regime, reason: fromSummary[2] ?? "" } : null;
}

/** BUY / SELL / NO_TRADE for the latest completed evaluation. */
export function decisionOf(e: Evaluation | null | undefined): "BUY" | "SELL" | "NO_TRADE" | null {
  if (!e) return null;
  if (e.outcome !== "SIGNAL") return "NO_TRADE";
  return /^SELL/.test(e.summary) ? "SELL" : "BUY";
}

const RISK_KEYS = ["risk_per_trade_pct", "max_daily_loss_pct", "max_open_positions"] as const;

export const RISK_CAP_LABEL: Record<(typeof RISK_KEYS)[number], string> = {
  risk_per_trade_pct: "Risk per trade (max, % of balance)",
  max_daily_loss_pct: "Daily loss limit (max, %)",
  max_open_positions: "Open positions (max)",
};

/** The strategy's own risk caps (they only tighten your risk profile). */
export function riskCaps(params: Record<string, unknown> | null | undefined): { key: keyof typeof RISK_CAP_LABEL; label: string; value: string }[] {
  return RISK_KEYS.filter((k) => params && params[k] !== undefined && params[k] !== null).map((k) => ({
    key: k,
    label: RISK_CAP_LABEL[k],
    value: k === "max_open_positions" ? String(params![k]) : `${params![k]}%`,
  }));
}

/** The latest version's parameters with the engine's descriptions (risk caps listed separately). */
export function parameterRows(s: Strategy): { key: string; label: string; value: string; description?: string }[] {
  if (s.key === "rules") return [];
  const params = (latestVersion(s)?.parameters ?? {}) as Record<string, unknown>;
  const schema: Record<string, JsonSchemaProperty> = s.parameter_schema?.properties ?? {};
  return Object.entries(params)
    .filter(([k]) => !(RISK_KEYS as readonly string[]).includes(k))
    .map(([key, value]) => ({
      key,
      label: schema[key]?.title ?? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
      value: typeof value === "boolean" ? (value ? "yes" : "no") : String(value),
      description: schema[key]?.description,
    }));
}

/** One line for the demo-forward-testing gate. */
export function gateSummary(v: ValidationGate | null | undefined): { ok: boolean; text: string } | null {
  if (!v) return null;
  if (v.qualifies_for_demo_forward_testing) return { ok: true, text: "Qualifies for demo forward testing (not a claim of profit)." };
  return { ok: false, text: `Does not qualify for demo forward testing: ${v.reasons.join("; ")}.` };
}
