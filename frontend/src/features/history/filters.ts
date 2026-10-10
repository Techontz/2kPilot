/**
 * History filters → API query (GET /api/history) and the CSV export URL
 * (GET /api/history/export?format=csv&…). Pure, so they are unit-tested.
 */

export type OutcomeFilter = "" | "win" | "loss" | "even";
export type RangePreset = "today" | "7d" | "30d" | "90d" | "all" | "custom";

export interface HistoryFilters {
  /** YYYY-MM-DD (inclusive), "" = no bound. */
  from: string;
  to: string;
  accountId: string;
  strategyId: string;
  outcome: OutcomeFilter;
}

export const EMPTY_FILTERS: HistoryFilters = { from: "", to: "", accountId: "", strategyId: "", outcome: "" };

export const OUTCOME_OPTIONS: { value: OutcomeFilter; label: string }[] = [
  { value: "", label: "All results" },
  { value: "win", label: "Profit" },
  { value: "loss", label: "Loss" },
  { value: "even", label: "Break-even" },
];

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Query parameters for /history and /history/export (empty filters are left out). */
export function historyQuery(filters: HistoryFilters, extra: Record<string, string | number> = {}): Record<string, string | number> {
  const query: Record<string, string | number> = {};
  if (filters.accountId) query.account_id = filters.accountId;
  if (filters.strategyId) query.strategy_id = filters.strategyId;
  if (DATE.test(filters.from)) query.from = filters.from;
  if (DATE.test(filters.to)) query.to = filters.to;
  if (filters.outcome) query.outcome = filters.outcome;
  return { ...query, ...extra };
}

/** Same-origin download link for the CSV with the current filters. */
export function exportUrl(filters: HistoryFilters): string {
  const params = new URLSearchParams({ format: "csv" });
  for (const [key, value] of Object.entries(historyQuery(filters))) params.set(key, String(value));
  return `/api/history/export?${params.toString()}`;
}

function ymd(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Date range for a preset, in UTC days (the API filters on exit time). */
export function presetRange(preset: RangePreset, now: Date = new Date()): { from: string; to: string } {
  const today = ymd(now);
  const daysAgo = (n: number) => ymd(new Date(now.getTime() - n * 86_400_000));
  switch (preset) {
    case "today":
      return { from: today, to: today };
    case "7d":
      return { from: daysAgo(6), to: today };
    case "30d":
      return { from: daysAgo(29), to: today };
    case "90d":
      return { from: daysAgo(89), to: today };
    default:
      return { from: "", to: "" };
  }
}

/** Which preset (if any) a range corresponds to — for the select's current value. */
export function detectPreset(filters: Pick<HistoryFilters, "from" | "to">, now: Date = new Date()): RangePreset {
  for (const preset of ["today", "7d", "30d", "90d", "all"] as const) {
    const r = presetRange(preset, now);
    if (r.from === filters.from && r.to === filters.to) return preset;
  }
  return "custom";
}

/** "from" after "to" is a mistake worth saying out loud. */
export function rangeProblem(filters: Pick<HistoryFilters, "from" | "to">): string | null {
  if (DATE.test(filters.from) && DATE.test(filters.to) && filters.from > filters.to) return "The start date is after the end date.";
  return null;
}
