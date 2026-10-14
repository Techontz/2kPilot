import type { JsonSchemaProperty, Strategy } from "@/lib/types";
import { latestVersion } from "./strategyUtils";

export interface ParamField {
  key: string;
  label: string;
  help?: string;
  kind: "number" | "integer" | "choice" | "toggle";
  options?: string[];
  min?: number;
  max?: number;
  group: "trading" | "signal";
}

/** Plain-English names for the settings people change most; the rest use the schema's title. */
const LABELS: Record<string, string> = {
  max_open_positions: "Trades open at once (max)",
  risk_per_trade_pct: "Risk per trade (max, % of balance)",
  max_daily_loss_pct: "Daily loss limit (max, %)",
  min_adx: "Minimum trend strength (ADX)",
  sideways_adx: "Below this ADX the market counts as sideways",
  reward_risk: "Target as a multiple of the stop",
  stop_atr_mult: "Stop distance (× ATR)",
  entry_timeframe: "Entry timeframe",
  trend_timeframe: "Trend timeframe",
};

/** Settings that decide how much and how often it trades — shown first. */
const TRADING = ["max_open_positions", "risk_per_trade_pct", "max_daily_loss_pct", "min_adx", "reward_risk", "stop_atr_mult"];

function enumOf(prop: JsonSchemaProperty, defs: Record<string, { enum?: string[] }> | undefined): string[] | undefined {
  if (prop.enum) return prop.enum;
  const ref = prop.$ref ?? prop.allOf?.[0]?.$ref;
  return ref ? defs?.[ref.split("/").pop() ?? ""]?.enum : undefined;
}

/** The form for a code strategy's parameters, built from its schema. Rule-based strategies use the builder. */
export function paramFields(s: Strategy): ParamField[] {
  const props = s.parameter_schema?.properties ?? {};
  const defs = s.parameter_schema?.$defs;
  const fields: ParamField[] = [];
  for (const [key, prop] of Object.entries(props)) {
    const options = enumOf(prop, defs);
    const kind: ParamField["kind"] | null = options
      ? "choice"
      : prop.type === "integer"
        ? "integer"
        : prop.type === "number"
          ? "number"
          : prop.type === "boolean"
            ? "toggle"
            : null;
    if (!kind) continue; // lists/objects aren't edited here
    fields.push({
      key,
      label: LABELS[key] ?? prop.title ?? key.replace(/_/g, " "),
      help: prop.description,
      kind,
      options,
      min: prop.minimum,
      max: prop.maximum,
      group: TRADING.includes(key) ? "trading" : "signal",
    });
  }
  return fields.sort((a, b) => (a.group === b.group ? (TRADING.indexOf(a.key) + 1 || 99) - (TRADING.indexOf(b.key) + 1 || 99) : a.group === "trading" ? -1 : 1));
}

/** Current values as text for the inputs: the latest version's, else the schema default. */
export function initialValues(s: Strategy, fields: ParamField[]): Record<string, string> {
  const params = (latestVersion(s)?.parameters ?? {}) as Record<string, unknown>;
  const props = s.parameter_schema?.properties ?? {};
  const out: Record<string, string> = {};
  for (const f of fields) {
    const v = params[f.key] ?? props[f.key]?.default;
    out[f.key] = v === undefined || v === null ? "" : String(v);
  }
  return out;
}

/**
 * The parameters to save: the latest version's (so nothing unedited is lost) with
 * the form's values typed. Errors are keyed by field.
 */
export function buildParameters(
  s: Strategy,
  fields: ParamField[],
  values: Record<string, string>,
): { parameters: Record<string, unknown>; errors: Record<string, string> } {
  const parameters: Record<string, unknown> = { ...((latestVersion(s)?.parameters ?? {}) as Record<string, unknown>) };
  const errors: Record<string, string> = {};
  for (const f of fields) {
    const raw = (values[f.key] ?? "").trim();
    if (f.kind === "choice") {
      if (f.options && !f.options.includes(raw)) errors[f.key] = "Choose one of the options.";
      else parameters[f.key] = raw;
      continue;
    }
    if (f.kind === "toggle") {
      parameters[f.key] = raw === "true";
      continue;
    }
    const n = Number(raw);
    if (raw === "" || !Number.isFinite(n)) errors[f.key] = "Enter a number.";
    else if (f.kind === "integer" && !Number.isInteger(n)) errors[f.key] = "Enter a whole number.";
    else if (f.min !== undefined && n < f.min) errors[f.key] = `At least ${f.min}.`;
    else if (f.max !== undefined && n > f.max) errors[f.key] = `At most ${f.max}.`;
    else parameters[f.key] = n;
  }
  return { parameters, errors };
}

/** Which settings differ from the latest version, for the version note. */
export function changedKeys(s: Strategy, parameters: Record<string, unknown>): string[] {
  const before = (latestVersion(s)?.parameters ?? {}) as Record<string, unknown>;
  return Object.keys(parameters).filter((k) => String(before[k]) !== String(parameters[k]));
}
