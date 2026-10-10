import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";
import { directionIsUp, directionLabel } from "@/lib/contracts";
import { cn } from "@/lib/utils";
import type { AccountEnvironment, ConnectionStatus, Trade } from "@/lib/types";

export type Tone = "neutral" | "positive" | "negative" | "warning" | "info" | "live" | "demo" | "primary";

const TONE: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground ring-border",
  positive: "bg-positive-soft text-positive ring-positive/25",
  negative: "bg-negative-soft text-negative ring-negative/25",
  warning: "bg-warning-soft text-warning ring-warning/25",
  info: "bg-info-soft text-info ring-info/25",
  live: "bg-live text-live-foreground ring-live/40",
  demo: "bg-transparent text-demo ring-demo/50",
  primary: "bg-primary/10 text-brand-ink ring-primary/25",
};

const DOT: Record<Tone, string> = {
  neutral: "bg-fg-subtle",
  positive: "bg-positive",
  negative: "bg-negative",
  warning: "bg-warning",
  info: "bg-info",
  live: "bg-live-foreground",
  demo: "bg-demo",
  primary: "bg-primary",
};

/** Small status pill (shadcn badge proportions, semantic 2kPilot colours). */
export function Pill({ tone = "neutral", dot, className, children, title }: { tone?: Tone; dot?: boolean; className?: string; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-[22px] w-fit shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold whitespace-nowrap ring-1 ring-inset", TONE[tone], className)}>
      {dot && <span className={cn("size-1.5 rounded-full", DOT[tone])} aria-hidden />}
      {children}
    </span>
  );
}

const ENV: Record<AccountEnvironment, { tone: Tone; label: string; title: string }> = {
  PAPER: { tone: "neutral", label: "PAPER", title: "Simulated by 2kPilot — no money" },
  DEMO: { tone: "demo", label: "DEMO", title: "Demo account — virtual money" },
  LIVE: { tone: "live", label: "LIVE", title: "LIVE account — REAL MONEY" },
  UNKNOWN: { tone: "warning", label: "UNKNOWN", title: "The broker did not confirm demo or live — never trades" },
};

/** PAPER / DEMO (calm) vs LIVE (loud, real money). */
export function EnvBadge({ env, className }: { env: AccountEnvironment; className?: string }) {
  const e = ENV[env];
  return (
    <Pill tone={e.tone} title={e.title} className={cn("font-bold tracking-[0.06em]", env === "LIVE" && "font-extrabold tracking-[0.1em]", className)}>
      {e.label}
    </Pill>
  );
}

const CONN: Record<ConnectionStatus, { tone: Tone; label: string }> = {
  CONNECTED: { tone: "positive", label: "Connected" },
  DISCONNECTED: { tone: "neutral", label: "Disconnected" },
  RECONNECTING: { tone: "warning", label: "Reconnecting" },
  ERROR: { tone: "negative", label: "Connection error" },
};

export function connectionLabel(status: ConnectionStatus): string {
  return CONN[status].label;
}

/** Status dot with an accessible label. */
export function ConnectionDot({ status }: { status: ConnectionStatus }) {
  const tone = CONN[status].tone;
  return (
    <span className="relative flex size-2.5 shrink-0" role="img" aria-label={CONN[status].label}>
      {status === "CONNECTED" && <span className="absolute inline-flex size-full rounded-full bg-positive motion-safe:animate-pulse-ring" />}
      <span className={cn("relative inline-flex size-2.5 rounded-full", DOT[tone])} />
    </span>
  );
}

export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  return (
    <Pill tone={CONN[status].tone} dot>
      {CONN[status].label}
    </Pill>
  );
}

/** Won / Lost / Sold / Break-even / Open for a trade. */
export function OutcomeBadge({ trade }: { trade: Pick<Trade, "status" | "outcome" | "net_pnl"> }) {
  if (trade.status === "OPEN") return <Pill tone="info" dot>Open</Pill>;
  const pnl = Number(trade.net_pnl);
  if (trade.outcome === "WON") return <Pill tone="positive">Won</Pill>;
  if (trade.outcome === "LOST") return <Pill tone="negative">Lost</Pill>;
  if (trade.outcome === "CANCELLED") return <Pill tone="neutral">Cancelled</Pill>;
  if (trade.outcome === "SOLD") return <Pill tone={pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral"}>Closed early</Pill>;
  if (!Number.isFinite(pnl) || pnl === 0) return <Pill tone="neutral">Break-even</Pill>;
  return pnl > 0 ? <Pill tone="positive">Profit</Pill> : <Pill tone="negative">Loss</Pill>;
}

/** "↗ Rise" / "↘ Fall" / "Buy" / "Sell" with an arrow (text carries the meaning). */
export function Direction({ trade, className }: { trade: Pick<Trade, "side" | "contract_family" | "contract_type">; className?: string }) {
  const up = directionIsUp(trade);
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-xs font-semibold", up ? "text-positive" : "text-negative", className)}>
      <Icon className="size-3.5" aria-hidden />
      {directionLabel(trade)}
    </span>
  );
}

const SOURCE: Record<string, { label: string; tone: Tone }> = {
  template: { label: "Template", tone: "primary" },
  builder: { label: "Built by you", tone: "neutral" },
  ai: { label: "From description", tone: "info" },
  import: { label: "Imported", tone: "neutral" },
  copy: { label: "Your copy", tone: "neutral" },
  code: { label: "Built-in", tone: "primary" },
};

export function SourceBadge({ source }: { source?: string | null }) {
  const s = SOURCE[source ?? ""] ?? { label: "Strategy", tone: "neutral" as Tone };
  return <Pill tone={s.tone}>{s.label}</Pill>;
}

const LEVEL: Record<string, number> = { beginner: 1, intermediate: 2, advanced: 3 };

/** Neutral chip with a 1–3 bar meter — difficulty is not a status, so no status colour. */
export function DifficultyBadge({ level }: { level?: string | null }) {
  if (!level) return null;
  const bars = LEVEL[level] ?? 0;
  return (
    <Pill tone="neutral" className="text-fg-muted">
      {bars > 0 && (
        <span aria-hidden className="flex items-end gap-[2px]">
          {[1, 2, 3].map((b) => <span key={b} className={cn("w-[3px] rounded-[1px]", b <= bars ? "bg-brand-ink" : "bg-line-strong")} style={{ height: 4 + b * 2 }} />)}
        </span>
      )}
      {level.charAt(0).toUpperCase() + level.slice(1)}
    </Pill>
  );
}
