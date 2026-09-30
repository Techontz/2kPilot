"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

interface Bar {
  label: string;
  value: number;
  detail?: string;
}

/**
 * Vertical bars around a zero baseline (profit up, loss down). Values are
 * printed in the tooltip and table views — colour is never the only cue.
 */
export function BarChart({ bars, height = 180, format, label }: { bars: Bar[]; height?: number; format: (v: number) => string; label: string }) {
  const [active, setActive] = useState<number | null>(null);
  if (!bars.length) return null;
  const max = Math.max(...bars.map((b) => Math.abs(b.value)), 1e-9);
  const hasNeg = bars.some((b) => b.value < 0);
  const hasPos = bars.some((b) => b.value > 0);
  const zero = hasNeg && hasPos ? 0.5 : hasNeg ? 0 : 1; // fraction from top where 0 sits
  const plot = height - 20;
  const current = active !== null ? bars[active] : null;

  return (
    <figure aria-label={label} className="relative">
      <div className="pointer-events-none h-5 text-xs text-fg-muted">
        {current && (
          <>
            <span className="num font-semibold text-fg">{format(current.value)}</span> · {current.label}
            {current.detail && <> · {current.detail}</>}
          </>
        )}
      </div>
      <div className="relative flex items-stretch gap-[2px]" style={{ height: plot }} onMouseLeave={() => setActive(null)}>
        <div className="pointer-events-none absolute right-0 left-0 border-t border-line-strong" style={{ top: `${zero * 100}%` }} />
        {bars.map((b, i) => {
          const h = (Math.abs(b.value) / max) * (hasNeg && hasPos ? 0.5 : 1) * 100;
          const up = b.value >= 0;
          return (
            <button
              key={b.label}
              type="button"
              aria-label={`${b.label}: ${format(b.value)}`}
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              className="relative flex-1 focus:outline-none"
            >
              <span
                className={cn(
                  "absolute right-0 left-0 mx-auto max-w-8 transition-opacity",
                  up ? "rounded-t-[4px] bg-positive" : "rounded-b-[4px] bg-negative",
                  active !== null && active !== i && "opacity-50",
                )}
                style={up ? { bottom: `${(1 - zero) * 100}%`, height: `${h}%` } : { top: `${zero * 100}%`, height: `${h}%` }}
              />
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-fg-subtle">
        <span>{bars[0]!.label}</span>
        <span>{bars[bars.length - 1]!.label}</span>
      </div>
    </figure>
  );
}
