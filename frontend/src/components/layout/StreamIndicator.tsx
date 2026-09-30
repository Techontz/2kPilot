"use client";

import { useStream } from "@/components/providers/StreamProvider";
import { cn } from "@/lib/cn";

/** Small dot telling the user whether the dashboard is receiving live updates. */
export function StreamIndicator() {
  const { connected } = useStream();
  return (
    <span className="hidden items-center gap-1.5 text-xs text-fg-subtle md:flex" title={connected ? "Live updates connected" : "Live updates reconnecting"}>
      <span className={cn("size-1.5 rounded-full", connected ? "bg-positive" : "bg-warning")} aria-hidden />
      {connected ? "Live" : "Reconnecting"}
    </span>
  );
}
