"use client";

import type { ReactNode } from "react";

/** Shared hover card for Recharts charts: value first (tabular), then context. */
export function ChartTooltipCard({ title, value, detail, tone }: { title: ReactNode; value: ReactNode; detail?: ReactNode; tone?: "positive" | "negative" }) {
  return (
    <div className="rounded-md bg-popover px-3 py-2 text-xs shadow-overlay ring-1 ring-line">
      <p className={tone === "positive" ? "num text-sm font-extrabold text-positive" : tone === "negative" ? "num text-sm font-extrabold text-negative" : "num text-sm font-extrabold text-fg"}>
        {value}
      </p>
      <p className="mt-0.5 text-fg-muted">{title}</p>
      {detail && <p className="text-fg-subtle">{detail}</p>}
    </div>
  );
}
