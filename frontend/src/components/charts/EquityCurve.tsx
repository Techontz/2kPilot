"use client";

import { useId } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltipCard } from "./ChartTooltip";
import type { SeriesPoint } from "./series";
import { useChartColors } from "./theme";

interface EquityCurveProps {
  data: SeriesPoint[];
  /** Accessible name, e.g. "Equity curve". */
  label: string;
  height?: number;
  format?: (value: number) => string;
  /** "equity" (brand colour, filled down) or "drawdown" (loss colour, underwater). */
  variant?: "equity" | "drawdown";
}

const dateLabel = (t: number) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const dateTimeLabel = (t: number) =>
  new Date(t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** Single-series area chart with a crosshair tooltip. One axis, 2px line, recessive grid. */
export function EquityCurve({ data, label, height = 240, format = (v) => v.toFixed(2), variant = "equity" }: EquityCurveProps) {
  const c = useChartColors();
  const gradientId = useId().replace(/:/g, "");
  const color = variant === "drawdown" ? c.negative : c.accent;
  const last = data[data.length - 1];

  return (
    <figure aria-label={label} className="min-w-0">
      {last && (
        <figcaption className="mb-2 text-xs text-fg-muted">
          <span className="num text-base font-extrabold text-fg">{format(last.value)}</span> latest
        </figcaption>
      )}
      <div style={{ height }} role="img" aria-label={`${label}: ${data.length} points${last ? `, latest ${format(last.value)}` : ""}`}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1={variant === "drawdown" ? "1" : "0"} x2="0" y2={variant === "drawdown" ? "0" : "1"}>
                <stop offset="0%" stopColor={color} stopOpacity={0.32} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke={c.grid} strokeDasharray="3 5" />
            <XAxis dataKey="time" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={dateLabel}
              tick={{ fill: c.text, fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={32} />
            <YAxis tickFormatter={(v: number) => format(v)} tick={{ fill: c.text, fontSize: 11 }} tickLine={false} axisLine={false}
              width={64} domain={["auto", "auto"]} orientation="right" />
            <Tooltip
              cursor={{ stroke: c.text, strokeWidth: 1, strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                const p = active ? (payload?.[0]?.payload as SeriesPoint | undefined) : undefined;
                return p ? <ChartTooltipCard title={dateTimeLabel(p.time)} value={format(p.value)} /> : null;
              }}
            />
            <Area type="monotone" dataKey="value" stroke={color} strokeWidth={2.5} fill={`url(#${gradientId})`}
              baseValue={variant === "drawdown" ? "dataMax" : "dataMin"} isAnimationActive={false}
              activeDot={{ r: 4, stroke: c.surface, strokeWidth: 2, fill: color }} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
