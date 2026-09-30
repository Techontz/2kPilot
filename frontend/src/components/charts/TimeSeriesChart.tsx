"use client";

import {
  AreaSeries,
  ColorType,
  createChart,
  CrosshairMode,
  type IChartApi,
  LineSeries,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { chartColors } from "./theme";

interface Point {
  time: number;
  value: number;
}

interface TimeSeriesChartProps {
  data: Point[];
  label: string;
  /** "area" for equity, "drawdown" for a negative-only underwater curve. */
  variant?: "area" | "line" | "drawdown";
  height?: number;
  format?: (value: number) => string;
}

/** Single-series time chart with crosshair tooltip (one axis, thin 2px line). */
export function TimeSeriesChart({ data, label, variant = "area", height = 240, format = (v) => v.toFixed(2) }: TimeSeriesChartProps) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [hover, setHover] = useState<{ time: number; value: number } | null>(null);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const c = chartColors();
    const chart = createChart(el, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: c.text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: c.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true },
      crosshair: { mode: CrosshairMode.Magnet },
      handleScroll: false,
      handleScale: false,
    });
    const color = variant === "drawdown" ? c.negative : c.accent;
    const series =
      variant === "line"
        ? chart.addSeries(LineSeries, { color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false })
        : chart.addSeries(AreaSeries, {
            lineColor: color,
            lineWidth: 2,
            topColor: variant === "drawdown" ? `${color}10` : `${color}33`,
            bottomColor: variant === "drawdown" ? `${color}44` : `${color}00`,
            invertFilledArea: variant === "drawdown",
            priceLineVisible: false,
            lastValueVisible: false,
          });
    series.applyOptions({ priceFormat: { type: "custom", formatter: (v: number) => format(v) } });
    series.setData(data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((param) => {
      const point = param.seriesData.get(series) as { value?: number; time?: Time } | undefined;
      if (!param.time || !point || point.value === undefined) setHover(null);
      else setHover({ time: param.time as number, value: point.value });
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [data, height, variant, format]);

  const last = data[data.length - 1];
  const shown = hover ?? (last ? { time: last.time, value: last.value } : null);
  return (
    <figure className="relative" aria-label={label}>
      {shown && (
        <figcaption className="pointer-events-none absolute top-0 left-0 z-10 text-xs text-fg-muted">
          <span className="num text-sm font-semibold text-fg">{format(shown.value)}</span>{" "}
          <span>{new Date(shown.time * 1000).toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</span>
        </figcaption>
      )}
      <div ref={container} className="pt-6" style={{ height: height + 24 }} />
    </figure>
  );
}
