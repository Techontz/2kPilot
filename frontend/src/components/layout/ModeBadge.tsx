import { Badge } from "@/components/ui/Badge";
import { MODE_INFO } from "@/lib/status";
import type { TradingMode } from "@/lib/types";

export function ModeBadge({ mode }: { mode: TradingMode }) {
  const info = MODE_INFO[mode];
  return (
    <Badge tone={info.tone} dot className={mode === "LIVE" ? "font-bold tracking-wider" : undefined}>
      <span className="sr-only">Operating mode: </span>
      {info.label}
    </Badge>
  );
}
