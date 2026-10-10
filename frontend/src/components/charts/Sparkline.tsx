"use client";

import { useId } from "react";
import { Area, AreaChart, Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import { useChartColors } from "./theme";

interface SparklineProps {
  values: number[];
  /** Accessible summary, e.g. "Balance, last 7 days: up 2.1%". */
  label: string;
  /** Colour by direction (first → last) or force a tone. */
  tone?: "auto" | "positive" | "negative" | "neutral";
  height?: number;
  className?: string;
  /** Fill a soft gradient under the line (larger charts). */
  area?: boolean;
}

/** Tiny trend line for stat tiles. No axes, no hover — the tile carries the number. */
export function Sparkline({ values, label, tone = "auto", height = 32, className, area = false }: SparklineProps) {
  const c = useChartColors();
  const gradientId = useId().replace(/[^a-zA-Z0-9]/g, "");
  if (values.length < 2) return null;
  const first = values[0]!;
  const last = values[values.length - 1]!;
  const resolved = tone === "auto" ? (last > first ? "positive" : last < first ? "negative" : "neutral") : tone;
  const color = resolved === "positive" ? c.positive : resolved === "negative" ? c.negative : area ? c.accent : c.text;
  const data = values.map((value, i) => ({ i, value }));
  return (
    <div role="img" aria-label={label} className={className} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {area ? (
          <AreaChart data={data} margin={{ top: 4, right: 2, bottom: 2, left: 2 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Area type="monotone" dataKey="value" stroke={color} strokeWidth={2.5} fill={`url(#${gradientId})`} baseValue="dataMin" isAnimationActive={false} />
          </AreaChart>
        ) : (
          <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
