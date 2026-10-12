import type { Instrument } from "./types";

/** GET /markets/instruments — the markets a connected account's broker reports. */
export interface InstrumentsResponse {
  instruments: Instrument[];
  connection_status: string;
  simulated: boolean;
  /** When the list was last fetched from the broker (null: never). */
  synced_at?: string | null;
  /** Why the latest fetch from the broker failed; the list is then the last one stored. */
  sync_error?: string | null;
}

export interface MarketGroup {
  key: string;
  label: string;
  instruments: Instrument[];
}

const GROUPS: { key: string; label: string }[] = [
  { key: "volatility", label: "Volatility indices" },
  { key: "volatility-1s", label: "Volatility indices (1s)" },
  { key: "synthetic", label: "Other synthetic indices" },
  { key: "forex", label: "Forex" },
  { key: "indices", label: "Stock indices" },
  { key: "commodities", label: "Commodities" },
  { key: "crypto", label: "Cryptocurrencies" },
  { key: "stocks", label: "Stocks" },
  { key: "other", label: "Other" },
];

const VOLATILITY = /^Volatility (\d+) (\(1s\) )?Index$/i;

/** Deriv names its Volatility indices "Volatility 75 Index" / "Volatility 75 (1s) Index". */
function volatility(i: Instrument): { level: number; oneSecond: boolean } | null {
  if (i.category !== "synthetic") return null;
  const m = VOLATILITY.exec(i.description.trim());
  return m ? { level: Number(m[1]), oneSecond: Boolean(m[2]) } : null;
}

export function marketGroupKey(i: Instrument): string {
  const v = volatility(i);
  if (v) return v.oneSecond ? "volatility-1s" : "volatility";
  return GROUPS.some((g) => g.key === i.category) ? i.category : "other";
}

export function marketLabel(i: Instrument): string {
  return i.description || i.canonical || i.name;
}

/** Search text: name, code and group, plus "v75"/"vol 75" style shorthands. */
function haystack(i: Instrument): string {
  const v = volatility(i);
  const group = GROUPS.find((g) => g.key === marketGroupKey(i))?.label ?? "";
  const aliases = v ? `v${v.level} vol ${v.level} vix ${v.level}${v.oneSecond ? " 1s 1hz" : ""}` : "";
  return `${marketLabel(i)} ${i.name} ${i.canonical} ${group} ${aliases}`.toLowerCase();
}

export function matchesMarket(i: Instrument, query: string): boolean {
  const text = haystack(i);
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((word) => text.includes(word));
}

/** Instruments matching the query, grouped (Volatility first, by level) in display order. */
export function groupMarkets(instruments: Instrument[], query = ""): MarketGroup[] {
  const matching = instruments.filter((i) => matchesMarket(i, query));
  return GROUPS.map((g) => ({
    ...g,
    instruments: matching
      .filter((i) => marketGroupKey(i) === g.key)
      .sort((a, b) => (volatility(a)?.level ?? 0) - (volatility(b)?.level ?? 0) || marketLabel(a).localeCompare(marketLabel(b))),
  })).filter((g) => g.instruments.length > 0);
}

export function findMarket(instruments: Instrument[] | undefined, symbol: string): Instrument | undefined {
  return instruments?.find((i) => i.name === symbol || i.canonical === symbol);
}
