"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  LineSeries,
  LineStyle,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { useChartColors } from "@/components/charts/theme";
import type { Candle, Trade } from "@/lib/types";
import { type Bar, type ChartTimeframe, ema, toBars, tradeLines, tradeMarkers } from "./chartLogic";

interface Handles {
  chart: IChartApi;
  candles: ISeriesApi<"Candlestick">;
  fast: ISeriesApi<"Line">;
  slow: ISeriesApi<"Line">;
  markers: ISeriesMarkersPluginApi<Time>;
  lines: IPriceLine[];
  fitted: boolean;
}

const at = (t: number) => t as UTCTimestamp;

/**
 * A live candle chart with the robot's work drawn on it: an arrow where it bought
 * or sold, a dot with the result where each trade closed, and lines for the
 * entry, stop and target of trades still open. New candles slide in without
 * resetting the view (unless the market or timeframe changes).
 */
export function LiveChart({
  candles,
  trades,
  digits,
  timeframe,
  money,
  height,
  label,
}: {
  candles: Candle[];
  trades: Trade[];
  digits: number;
  timeframe: ChartTimeframe;
  money: (v: number) => string;
  height: number;
  label: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const handles = useRef<Handles | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const c = useChartColors();
  const bars = useMemo(() => toBars(candles), [candles]);

  // Build the chart once per market/timeframe/theme; data updates below reuse it.
  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const chart = createChart(el, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: c.text, fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 6 },
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
    const line = { lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false } as const;
    const fast = chart.addSeries(LineSeries, { ...line, color: c.accent });
    const slow = chart.addSeries(LineSeries, { ...line, color: c.text, lineStyle: LineStyle.Dashed });
    const markers = createSeriesMarkers(series, []);
    chart.subscribeCrosshairMove((param) => {
      const bar = param.seriesData.get(series) as Bar | undefined;
      setHover(param.time && bar ? { ...bar, time: param.time as number } : null);
    });
    handles.current = { chart, candles: series, fast, slow, markers, lines: [], fitted: false };
    return () => {
      handles.current = null;
      chart.remove();
    };
  }, [digits, height, c, label, timeframe]);

  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    h.candles.setData(bars.map((b) => ({ ...b, time: at(b.time) })));
    h.fast.setData(ema(bars, 20).map((p) => ({ ...p, time: at(p.time) })));
    h.slow.setData(ema(bars, 50).map((p) => ({ ...p, time: at(p.time) })));
    const color = { positive: c.positive, negative: c.negative, neutral: c.text };
    h.markers.setMarkers(
      tradeMarkers(trades, bars, timeframe, money).map((m) => ({ time: at(m.time), position: m.position, shape: m.shape, color: color[m.tone], text: m.text })),
    );
    for (const l of h.lines) h.candles.removePriceLine(l);
    h.lines = trades
      .filter((t) => t.status === "OPEN")
      .flatMap(tradeLines)
      .map((l) =>
        h.candles.createPriceLine({
          price: l.price,
          title: l.title,
          color: l.kind === "stop" ? c.negative : l.kind === "target" ? c.positive : c.accent,
          lineStyle: l.kind === "entry" ? LineStyle.Solid : LineStyle.Dashed,
          lineWidth: 1,
          axisLabelVisible: true,
        }),
      );
    if (!h.fitted && bars.length > 0) {
      h.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - 120), to: bars.length + 6 });
      h.fitted = true;
    }
  }, [bars, trades, timeframe, money, c]);

  const last = bars[bars.length - 1];
  const shown = hover ?? last ?? null;
  return (
    <figure aria-label={label} className="relative">
      {shown && (
        <figcaption className="num pointer-events-none absolute left-1 top-1 z-10 flex flex-wrap gap-x-3 text-xs text-fg-muted">
          {(["open", "high", "low", "close"] as const).map((k) => (
            <span key={k}>
              {k[0]!.toUpperCase()} <span className="text-fg">{shown[k].toFixed(digits)}</span>
            </span>
          ))}
          <span className="flex items-center gap-1"><span className="h-0.5 w-3 rounded bg-brand-ink" aria-hidden /> EMA 20</span>
          <span className="flex items-center gap-1"><span className="h-0.5 w-3 rounded border-t border-dashed border-fg-subtle" aria-hidden /> EMA 50</span>
        </figcaption>
      )}
      <div ref={container} style={{ height }} />
    </figure>
  );
}
