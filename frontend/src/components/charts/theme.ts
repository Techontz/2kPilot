/** Reads design tokens so charts match the UI (and any future theme). */
export function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim();
  return value || fallback;
}

export function chartColors() {
  return {
    text: token("fg-subtle", "#6b7486"),
    grid: token("line", "#222a36"),
    border: token("line-strong", "#2e3847"),
    accent: token("accent", "#7aa2ff"),
    positive: token("positive", "#34c28a"),
    negative: token("negative", "#ef5f6b"),
    surface: token("surface", "#10141b"),
  };
}

/** lightweight-charts wants ascending, unique UTC-second timestamps. */
export function toSeries<T>(rows: T[], time: (r: T) => string, value: (r: T) => number | null) {
  const out: { time: number; value: number }[] = [];
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
