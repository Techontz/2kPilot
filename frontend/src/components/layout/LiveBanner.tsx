import { TriangleAlert } from "lucide-react";
import type { TradingMode } from "@/lib/types";

/** Persistent, unmissable indicator whenever the system is in LIVE mode. */
export function LiveBanner({ mode }: { mode: TradingMode }) {
  if (mode !== "LIVE") return null;
  return (
    <div
      role="alert"
      className="sticky top-0 z-40 flex items-center justify-center gap-2 bg-live px-4 py-1.5 text-xs font-bold tracking-[0.18em] text-white uppercase"
    >
      <TriangleAlert aria-hidden className="size-3.5" />
      Live mode — real money at risk
      <TriangleAlert aria-hidden className="size-3.5" />
    </div>
  );
}
