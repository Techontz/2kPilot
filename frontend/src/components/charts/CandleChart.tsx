"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import type { CandlePoint } from "@/lib/types";
import { chartColors } from "./theme";

interface OHLC {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export function CandleChart({ candles, digits, height = 360, label }: { candles: CandlePoint[]; digits: number; height?: number; label: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<OHLC | null>(null);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const c = chartColors();
    const chart = createChart(el, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: c.text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true },
      crosshair: { mode: CrosshairMode.Normal },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: c.positive,
      downColor: c.negative,
      wickUpColor: c.positive,
      wickDownColor: c.negative,
      borderVisible: false,
      priceFormat: { type: "price", precision: digits, minMove: 1 / 10 ** digits },
    });
    const data: OHLC[] = [];
    for (const k of candles) {
      const t = Math.floor(new Date(k.time).getTime() / 1000);
      if (data.length && t <= data[data.length - 1]!.time) continue;
      data.push({ time: t, open: +k.open, high: +k.high, low: +k.low, close: +k.close });
    }
    series.setData(data.map((d) => ({ ...d, time: d.time as UTCTimestamp })));
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((param) => {
      const bar = param.seriesData.get(series) as OHLC | undefined;
      setHover(param.time && bar ? { ...bar, time: param.time as number } : null);
    });
    return () => chart.remove();
  }, [candles, digits, height]);

  const last = candles[candles.length - 1];
  const shown = hover ?? (last ? { time: 0, open: +last.open, high: +last.high, low: +last.low, close: +last.close } : null);
  return (
    <figure aria-label={label}>
      {shown && (
        <figcaption className="num mb-2 flex flex-wrap gap-x-4 text-xs text-fg-muted">
          {(["open", "high", "low", "close"] as const).map((k) => (
            <span key={k}>
              {k[0]!.toUpperCase()} <span className="text-fg">{shown[k].toFixed(digits)}</span>
            </span>
          ))}
        </figcaption>
      )}
      <div ref={container} style={{ height }} />
    </figure>
  );
}
