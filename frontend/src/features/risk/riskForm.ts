/**
 * Risk profile form: which fields exist, how they are explained, and how the
 * form converts to/from the API (backend/app/Http/Requests/RiskProfileRequest.php).
 * An empty optional field means "this limit is off" (sent as null).
 */

import type { GlossaryKey } from "@/lib/glossary";
import type { RiskProfile } from "@/lib/types";

export type LimitUnit = "money" | "pct" | "count" | "lots" | "pips" | "ratio" | "minutes" | "seconds";

export interface LimitField {
  key: keyof RiskProfile & string;
  label: string;
  unit: LimitUnit;
  help: string;
  required?: boolean;
  term?: GlossaryKey;
}

/** The stake-based limits a beginner needs (Deriv contracts and Paper). */
export const BASIC_FIELDS: LimitField[] = [
  { key: "stake_amount", label: "Stake per trade", unit: "money", required: true, term: "stake", help: "What each trade risks. A Rise/Fall or Multiplier trade can never lose more than its stake." },
  { key: "max_stake_amount", label: "Largest stake on one trade", unit: "money", help: "A hard cap: no single trade may stake more than this, whatever a strategy asks for." },
  { key: "max_daily_loss_amount", label: "Daily loss limit", unit: "money", help: "Stop trading for the day after losing this much (closed and open trades)." },
  { key: "max_daily_loss_pct", label: "Daily loss limit (% of balance)", unit: "pct", help: "The same, as a share of the balance. Whichever limit is reached first applies." },
  { key: "max_consecutive_losses", label: "Stop after losses in a row", unit: "count", term: "losingStreak", help: "Stop for the day after this many losing trades in a row." },
  { key: "daily_profit_target_amount", label: "Daily profit target", unit: "money", help: "Stop for the day after making this much — keeps a good day good." },
  { key: "max_trades_per_day", label: "Trades per day", unit: "count", help: "The most trades a day. Prevents over-trading." },
  { key: "max_open_positions", label: "Trades open at once", unit: "count", help: "The most trades open at the same time on the account." },
];

/** Spot (lots/pips) limits — used by Spot trades on Paper. */
export const ADVANCED_GROUPS: { title: string; fields: LimitField[] }[] = [
  { title: "Per trade (Spot)", fields: [
    { key: "risk_per_trade_pct", label: "Risk per trade", unit: "pct", required: true, help: "Money lost if the stop loss is hit, as % of equity. Spot position size is calculated from this." },
    { key: "max_position_lots", label: "Largest position", unit: "lots", term: "lot", help: "Upper cap per position, whatever the sizing says." },
    { key: "min_stop_pips", label: "Shortest stop loss", unit: "pips", term: "pip", help: "Stops closer than this are too easily hit by noise." },
    { key: "max_stop_pips", label: "Longest stop loss", unit: "pips", help: "Very wide stops mean very small positions." },
    { key: "min_reward_risk", label: "Minimum reward:risk", unit: "ratio", term: "riskReward", help: "e.g. 1.5 = the target must be at least 1.5 times the stop distance." },
  ] },
  { title: "Loss limits", fields: [
    { key: "max_weekly_loss_pct", label: "Weekly loss limit", unit: "pct", help: "Stop for the week once losses reach this (week starts Monday 00:00 UTC)." },
    { key: "max_drawdown_pct", label: "Maximum drawdown", unit: "pct", term: "drawdown", help: "Hitting this switches trading off for the account until you review it." },
    { key: "cooldown_after_losses", label: "Pause after losses in a row", unit: "count", help: "Start a pause after this many losses in a row…" },
    { key: "cooldown_minutes", label: "Pause length", unit: "minutes", help: "…for this long. Set both or neither." },
  ] },
  { title: "Exposure", fields: [
    { key: "max_positions_per_symbol", label: "Positions per symbol", unit: "count", help: "Avoid stacking trades on one instrument." },
    { key: "max_symbol_exposure_lots", label: "Size open on one symbol", unit: "lots", help: "Total lots open on one symbol." },
    { key: "max_total_exposure_lots", label: "Size open on the account", unit: "lots", help: "Total lots open on the whole account." },
    { key: "max_total_risk_pct", label: "Total open risk", unit: "pct", term: "openRisk", help: "Sum of the risk of all open trades, as % of equity." },
  ] },
  { title: "Market conditions", fields: [
    { key: "max_spread_pips", label: "Spread protection", unit: "pips", term: "spread", help: "Skip trades when the spread is wider than this." },
    { key: "max_slippage_pips", label: "Slippage protection", unit: "pips", help: "Largest price difference accepted when the order fills." },
    { key: "max_data_age_seconds", label: "Oldest price allowed", unit: "seconds", required: true, help: "Never trade on a stale price." },
  ] },
];

export const SESSIONS = ["ASIA", "LONDON", "OVERLAP", "NEW_YORK"] as const;

export const ALL_FIELDS: LimitField[] = [...BASIC_FIELDS, ...ADVANCED_GROUPS.flatMap((g) => g.fields)];

export interface ProfileForm {
  name: string;
  values: Record<string, string>;
  sessions: string[];
  hoursStart: string;
  hoursEnd: string;
}

/** Defaults for a new profile: the Beginner limits. */
export const NEW_PROFILE_VALUES: Record<string, string> = {
  stake_amount: "1",
  max_stake_amount: "5",
  max_consecutive_losses: "3",
  max_trades_per_day: "20",
  max_open_positions: "3",
  max_daily_loss_pct: "2",
  risk_per_trade_pct: "0.5",
  max_weekly_loss_pct: "4",
  max_drawdown_pct: "10",
  max_data_age_seconds: "120",
  min_stop_pips: "8",
  max_stop_pips: "150",
  min_reward_risk: "1.5",
  max_spread_pips: "2.5",
};

/** "2.000" → "2", "0.500" → "0.5", null → "" (decimal strings, never floats in maths). */
export function trimDecimal(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text;
  return text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text;
}

export function toForm(profile: RiskProfile | null): ProfileForm {
  if (!profile) {
    return { name: "", values: { ...NEW_PROFILE_VALUES }, sessions: ["LONDON", "OVERLAP", "NEW_YORK"], hoursStart: "", hoursEnd: "" };
  }
  const values: Record<string, string> = {};
  for (const f of ALL_FIELDS) values[f.key] = trimDecimal(profile[f.key] as string | number | null);
  return {
    name: profile.name,
    values,
    sessions: [...profile.allowed_sessions],
    hoursStart: profile.trading_hours_start?.slice(0, 5) ?? "",
    hoursEnd: profile.trading_hours_end?.slice(0, 5) ?? "",
  };
}

export function toBody(form: ProfileForm): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: form.name.trim(),
    allowed_sessions: form.sessions,
    trading_hours_start: form.hoursStart || null,
    trading_hours_end: form.hoursEnd || null,
  };
  for (const f of ALL_FIELDS) {
    const v = (form.values[f.key] ?? "").trim().replace(",", ".");
    body[f.key] = v === "" ? null : v;
  }
  return body;
}

/** Fields with a validation error that live in the Advanced section (to open it). */
export function advancedErrorKeys(errors: Record<string, string[]>): string[] {
  const advanced = new Set<string>([...ADVANCED_GROUPS.flatMap((g) => g.fields.map((f) => f.key)), "allowed_sessions", "trading_hours_start", "trading_hours_end"]);
  return Object.keys(errors).filter((k) => advanced.has(k.split(".")[0]!));
}

export function unitLabel(unit: LimitUnit, currency?: string | null): string {
  switch (unit) {
    case "money": return currency ?? "account currency";
    case "pct": return "%";
    case "count": return "";
    case "lots": return "lots";
    case "pips": return "pips";
    case "ratio": return "× risk";
    case "minutes": return "minutes";
    case "seconds": return "seconds";
  }
}
