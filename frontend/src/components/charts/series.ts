/** A point on a time series: UTC seconds + value. */
export interface SeriesPoint {
  time: number;
  value: number;
}

/** Ascending, unique UTC-second points (later duplicates win); bad rows are dropped. */
export function toSeries<T>(rows: T[], time: (r: T) => string, value: (r: T) => number | null): SeriesPoint[] {
  const out: SeriesPoint[] = [];
  for (const r of rows) {
    const v = value(r);
    if (v === null || !Number.isFinite(v)) continue;
    const t = Math.floor(new Date(time(r)).getTime() / 1000);
    if (!Number.isFinite(t)) continue;
    const last = out[out.length - 1];
    if (last && t <= last.time) {
      if (t === last.time) last.value = v;
      continue;
    }
    out.push({ time: t, value: v });
  }
  return out;
}

export interface PnlBar {
  label: string;
  value: number;
  detail?: string;
}

/** Recharts-friendly rows for daily P/L bars: sign drives colour, label stays text. */
export function toPnlRows(bars: PnlBar[]) {
  return bars.map((b) => ({ ...b, positive: b.value >= 0 }));
}

/** Y-domain that always includes zero so bars are anchored to the baseline. */
export function zeroAnchoredDomain(values: number[]): [number, number] {
  if (!values.length) return [0, 1];
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  return min === max ? [0, 1] : [min, max];
}
