"use client";

import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltipCard } from "./ChartTooltip";
import { type PnlBar, toPnlRows, zeroAnchoredDomain } from "./series";
import { useChartColors } from "./theme";

interface PnlBarsProps {
  bars: PnlBar[];
  label: string;
  format: (value: number) => string;
  height?: number;
}

/**
 * Daily (or monthly) P/L bars around a zero baseline: profit up in green, loss
 * down in red. The value is always given as text in the tooltip and the
 * screen-reader list — colour is never the only cue.
 */
export function PnlBars({ bars, label, format, height = 200 }: PnlBarsProps) {
  const c = useChartColors();
  if (!bars.length) return null;
  const rows = toPnlRows(bars);

  return (
    <figure aria-label={label} className="min-w-0">
      <div style={{ height }} aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap={3}>
            <XAxis dataKey="label" tick={{ fill: c.text, fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis domain={zeroAnchoredDomain(rows.map((r) => r.value))} tickFormatter={(v: number) => format(v)}
              tick={{ fill: c.text, fontSize: 11 }} tickLine={false} axisLine={false} width={64} orientation="right" />
            <ReferenceLine y={0} stroke={c.border} strokeWidth={1.5} />
            <Tooltip
              cursor={{ fill: c.grid, opacity: 0.6 }}
              content={({ active, payload }) => {
                const p = active ? (payload?.[0]?.payload as (PnlBar & { positive: boolean }) | undefined) : undefined;
                return p ? <ChartTooltipCard title={p.label} value={format(p.value)} detail={p.detail} tone={p.positive ? "positive" : "negative"} /> : null;
              }}
            />
            <Bar dataKey="value" radius={5} maxBarSize={28} isAnimationActive={false}>
              {rows.map((r) => <Cell key={r.label} fill={r.positive ? c.positive : c.negative} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="sr-only">
        {rows.map((r) => <li key={r.label}>{`${r.label}: ${format(r.value)}${r.detail ? ` (${r.detail})` : ""}`}</li>)}
      </ul>
    </figure>
  );
}
