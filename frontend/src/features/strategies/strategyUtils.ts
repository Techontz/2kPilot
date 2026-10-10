import type { Strategy, StrategyVersion, Timeframe } from "@/lib/types";

const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];

export function latestVersion(strategy: Strategy): StrategyVersion | null {
  if (strategy.latest_version) return strategy.latest_version;
  return [...strategy.versions].sort((a, b) => b.version - a.version)[0] ?? null;
}

/** The candles the strategy decides on: the rule set's timeframe, else the suggestion, else M5. */
export function strategyTimeframe(strategy: Strategy): Timeframe {
  const params = latestVersion(strategy)?.parameters ?? {};
  const fromRules = (params as { timeframe?: unknown }).timeframe ?? (params as { entry_timeframe?: unknown }).entry_timeframe;
  if (typeof fromRules === "string" && TIMEFRAMES.includes(fromRules as Timeframe)) return fromRules as Timeframe;
  return strategy.details?.suggested_timeframe ?? "M5";
}

export function isRuleBased(strategy: Strategy): boolean {
  return strategy.key === "rules";
}

/** The user's own strategies (plus templates they activated directly). */
export function isMine(strategy: Strategy): boolean {
  return !strategy.built_in || strategy.assignments.length > 0;
}

/** A name not used by any of `taken` ("EMA crossover", "EMA crossover (2)", …). */
export function uniqueName(base: string, taken: string[]): string {
  const names = new Set(taken.map((n) => n.toLowerCase()));
  if (!names.has(base.toLowerCase())) return base.slice(0, 120);
  for (let i = 2; i < 1000; i++) {
    const candidate = `${base.slice(0, 110)} (${i})`;
    if (!names.has(candidate.toLowerCase())) return candidate;
  }
  return `${base.slice(0, 100)} (${Date.now()})`;
}

/** Plain-English rules for any strategy (rule sets have rules_text; code strategies their description). */
export function rulesText(strategy: Strategy): string {
  return strategy.rules_text ?? latestVersion(strategy)?.rules_text ?? strategy.summary ?? strategy.description;
}
