/**
 * Plain-English labels for contracts (Rise/Fall, Multipliers, Spot) — used on
 * Home, History, Strategies and the activate / backtest dialogs.
 */
import { formatCurrency } from "./format";
import type { ContractFamily, ContractOffer, ContractSpec, DurationUnit, Side, Trade } from "./types";

export const FAMILY_LABEL: Record<ContractFamily, string> = {
  RISE_FALL: "Rise/Fall",
  MULTIPLIER: "Multiplier",
  SPOT: "Spot",
};

export const FAMILY_HELP: Record<ContractFamily, string> = {
  RISE_FALL: "You pick a direction and a duration. If the price ends higher (Rise) or lower (Fall) than it started, you win the payout; otherwise you lose the stake. The stake is the most you can lose.",
  MULTIPLIER: "Profit and loss are the price move multiplied by the multiplier. It runs until it is closed (by a rule, a take profit or a stop loss). You can never lose more than the stake.",
  SPOT: "Paper only. A position in lots with a stop loss and a take profit, sized from your risk per trade.",
};

const UNIT_WORDS: Record<DurationUnit, [string, string]> = {
  t: ["tick", "ticks"],
  s: ["second", "seconds"],
  m: ["minute", "minutes"],
  h: ["hour", "hours"],
  d: ["day", "days"],
};

export const DURATION_UNITS: { value: DurationUnit; label: string }[] = [
  { value: "t", label: "Ticks" },
  { value: "s", label: "Seconds" },
  { value: "m", label: "Minutes" },
  { value: "h", label: "Hours" },
  { value: "d", label: "Days" },
];

export function durationText(duration: number | null | undefined, unit: DurationUnit | null | undefined): string {
  if (!duration || !unit) return "—";
  const [one, many] = UNIT_WORDS[unit];
  return `${duration} ${duration === 1 ? one : many}`;
}

const SECONDS: Record<Exclude<DurationUnit, "t">, number> = { s: 1, m: 60, h: 3600, d: 86400 };

/** "15s" / "1d" / "5t" (Deriv duration strings) → [amount, unit]. */
export function parseDuration(text: string): [number, DurationUnit] | null {
  const match = /^(\d+)([tsmhd])$/.exec(text.trim());
  return match ? [Number(match[1]), match[2] as DurationUnit] : null;
}

/** Is `duration unit` inside any of the broker's ranges? Ticks only compare with ticks. */
export function durationAllowed(duration: number, unit: DurationUnit, ranges: { min: string; max: string }[]): boolean {
  return ranges.some((r) => {
    const lo = parseDuration(r.min);
    const hi = parseDuration(r.max);
    if (!lo || !hi) return false;
    if (unit === "t" || lo[1] === "t" || hi[1] === "t") return unit === "t" && lo[1] === "t" && hi[1] === "t" && lo[0] <= duration && duration <= hi[0];
    const secs = duration * SECONDS[unit];
    return lo[0] * SECONDS[lo[1] as Exclude<DurationUnit, "t">] <= secs && secs <= hi[0] * SECONDS[hi[1] as Exclude<DurationUnit, "t">];
  });
}

/** "Rise/Fall · 25 minutes · stake $1.00" (stake from the risk profile when the spec has none). */
export function contractSummary(spec: Partial<ContractSpec> | null | undefined, opts: { currency?: string | null; profileStake?: string | number | null } = {}): string {
  if (!spec?.contract_family) return "—";
  const parts: string[] = [FAMILY_LABEL[spec.contract_family]];
  if (spec.contract_family === "RISE_FALL") parts.push(durationText(spec.duration, spec.duration_unit));
  if (spec.contract_family === "MULTIPLIER" && spec.multiplier) parts.push(`×${spec.multiplier}`);
  if (spec.contract_family !== "SPOT") {
    if (spec.stake) parts.push(`stake ${formatCurrency(spec.stake, opts.currency)}`);
    else if (opts.profileStake !== undefined && opts.profileStake !== null) parts.push(`stake ${formatCurrency(opts.profileStake, opts.currency)} (risk profile)`);
    else parts.push("stake from risk profile");
  } else {
    parts.push("sized by your risk per trade");
  }
  return parts.join(" · ");
}

/** Plain direction of a trade: "Rise" / "Fall" / "Up" / "Down" / "Buy" / "Sell". */
export function directionLabel(trade: Pick<Trade, "side" | "contract_family" | "contract_type">): string {
  const type = trade.contract_type ?? "";
  if (trade.contract_family === "RISE_FALL" || type.startsWith("CALL") || type.startsWith("PUT")) {
    return type.startsWith("PUT") || (!type && trade.side === "SELL") ? "Fall" : "Rise";
  }
  if (trade.contract_family === "MULTIPLIER" || type.startsWith("MULT")) {
    return type === "MULTDOWN" || (!type && trade.side === "SELL") ? "Down" : "Up";
  }
  return trade.side === "BUY" ? "Buy" : "Sell";
}

/** Direction tone: rising/buy = positive arrow, falling/sell = negative arrow. */
export function directionIsUp(trade: Pick<Trade, "side" | "contract_type">): boolean {
  const type = trade.contract_type ?? "";
  if (type.startsWith("PUT") || type === "MULTDOWN") return false;
  if (type.startsWith("CALL") || type === "MULTUP") return true;
  return trade.side === ("BUY" satisfies Side);
}

/** "Rise/Fall" or "Multiplier ×100" or "Spot" for a trade row. */
export function tradeContractLabel(trade: Pick<Trade, "contract_family" | "multiplier">): string {
  const family = trade.contract_family ?? "SPOT";
  if (family === "MULTIPLIER" && trade.multiplier) return `Multiplier ×${trade.multiplier}`;
  return FAMILY_LABEL[family];
}

/** Stake (contracts) or volume (Spot lots) as text. */
export function sizeText(trade: Pick<Trade, "stake" | "volume" | "contract_family">, currency?: string | null): string {
  if (trade.stake !== null && trade.stake !== undefined && trade.contract_family && trade.contract_family !== "SPOT") return formatCurrency(trade.stake, currency);
  const n = Number(trade.volume);
  return Number.isFinite(n) ? `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })} lots` : "—";
}

/** Fill defaults for a family so the spec is valid for the API (fields that don't apply are null). */
export function specForFamily(family: ContractFamily, from: Partial<ContractSpec> = {}): ContractSpec {
  return {
    contract_family: family,
    duration: family === "RISE_FALL" ? (from.duration ?? 5) : null,
    duration_unit: family === "RISE_FALL" ? (from.duration_unit ?? "m") : null,
    allow_equals: family === "RISE_FALL" ? Boolean(from.allow_equals) : false,
    stake: family === "SPOT" ? null : (from.stake ?? null),
    multiplier: family === "MULTIPLIER" ? (from.multiplier ?? null) : null,
    take_profit_amount: family === "MULTIPLIER" ? (from.take_profit_amount ?? null) : null,
    stop_loss_amount: family === "MULTIPLIER" ? (from.stop_loss_amount ?? null) : null,
  };
}


/** Families a symbol offers (no offer known = everything the account type can do). */
export function availableFamilies(offer: ContractOffer | null | undefined, isDeriv: boolean): ContractFamily[] {
  if (!offer) return isDeriv ? ["RISE_FALL", "MULTIPLIER"] : ["RISE_FALL", "MULTIPLIER", "SPOT"];
  const out: ContractFamily[] = [];
  if (offer.families.RISE_FALL.available) out.push("RISE_FALL");
  if (offer.families.MULTIPLIER.available) out.push("MULTIPLIER");
  if (offer.families.SPOT.available && !isDeriv) out.push("SPOT");
  return out;
}

/** The starting contract: the strategy's suggestion when the symbol offers it, else the broker's default. */
export function initialContract(suggested: Partial<ContractSpec> | null | undefined, offer: ContractOffer | null | undefined, isDeriv: boolean): ContractSpec {
  const families = availableFamilies(offer, isDeriv);
  const wanted = suggested?.contract_family;
  if (wanted && families.includes(wanted)) {
    const spec = specForFamily(wanted, suggested ?? {});
    if (wanted === "RISE_FALL" && offer && spec.duration && spec.duration_unit && !durationAllowed(spec.duration, spec.duration_unit, offer.families.RISE_FALL.durations)) {
      return specForFamily(wanted, offer.default_contract.contract_family === "RISE_FALL" ? offer.default_contract : { duration: 5, duration_unit: "m" });
    }
    if (wanted === "MULTIPLIER" && offer && (!spec.multiplier || !offer.families.MULTIPLIER.multipliers.includes(spec.multiplier))) {
      return specForFamily(wanted, { ...spec, multiplier: offer.families.MULTIPLIER.multipliers[0] ?? null });
    }
    return spec;
  }
  if (offer && families.includes(offer.default_contract.contract_family)) return specForFamily(offer.default_contract.contract_family, offer.default_contract);
  return specForFamily(families[0] ?? "SPOT");
}

/** Client-side contract checks (the broker check on the server stays the authority). */
export function contractProblems(spec: ContractSpec, offer: ContractOffer | null | undefined, opts: { isDeriv: boolean; maxStake?: number | null }): Partial<Record<keyof ContractSpec, string>> {
  const out: Partial<Record<keyof ContractSpec, string>> = {};
  const families = availableFamilies(offer, opts.isDeriv);
  if (!families.includes(spec.contract_family)) out.contract_family = `${FAMILY_LABEL[spec.contract_family]} is not offered here.`;
  if (spec.contract_family === "RISE_FALL") {
    if (!spec.duration || spec.duration < 1 || !Number.isInteger(spec.duration)) out.duration = "Enter a whole number of at least 1.";
    else if (offer && spec.duration_unit && !durationAllowed(spec.duration, spec.duration_unit, offer.families.RISE_FALL.durations)) {
      const ranges = rangesText(offer.families.RISE_FALL.durations);
      out.duration = `Not offered on this symbol (allowed: ${ranges || "none"}).`;
    }
    if (spec.allow_equals && offer && !offer.families.RISE_FALL.allow_equals) out.allow_equals = "“Win on equal prices” is not offered here.";
  }
  if (spec.contract_family === "MULTIPLIER") {
    if (!spec.multiplier) out.multiplier = "Choose a multiplier.";
    else if (offer && !offer.families.MULTIPLIER.multipliers.includes(spec.multiplier)) out.multiplier = `×${spec.multiplier} is not offered here.`;
    const sl = Number(spec.stop_loss_amount);
    const stake = Number(spec.stake);
    if (spec.stop_loss_amount && spec.stake && sl > stake) out.stop_loss_amount = "The stop loss can't be more than the stake (the most a contract can lose).";
    for (const key of ["take_profit_amount", "stop_loss_amount"] as const) {
      if (spec[key] !== null && spec[key] !== "" && !(Number(spec[key]) > 0)) out[key] = "Enter an amount above 0, or leave it empty.";
    }
  }
  if (spec.contract_family !== "SPOT" && spec.stake !== null && spec.stake !== "") {
    const stake = Number(spec.stake);
    if (!(stake > 0)) out.stake = "Enter a stake above 0, or leave it empty to use your risk profile.";
    else if (opts.maxStake && stake > opts.maxStake) out.stake = `Your risk profile allows at most ${opts.maxStake} per trade.`;
  }
  return out;
}

/** "900s" → "15 min", "1t" → "1 tick", "365d" → "365 days" (broker duration strings, for people). */
export function humanDuration(text: string): string {
  const parsed = parseDuration(text);
  if (!parsed) return text;
  let [n, unit] = parsed;
  if (unit === "s" && n % 60 === 0) [n, unit] = [n / 60, "m"];
  if (unit === "m" && n % 60 === 0) [n, unit] = [n / 60, "h"];
  if (unit === "h" && n % 24 === 0) [n, unit] = [n / 24, "d"];
  return durationText(n, unit);
}

/** "1 tick – 10 ticks, 15 minutes – 365 days" */
export function rangesText(ranges: { min: string; max: string }[]): string {
  return ranges.map((r) => `${humanDuration(r.min)} – ${humanDuration(r.max)}`).join(", ");
}
