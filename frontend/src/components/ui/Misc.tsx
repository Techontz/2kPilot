import { AlertTriangle, CircleCheck, Info, OctagonAlert } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { pnlTone } from "@/lib/format";
import type { AccountEnvironment, ConnectionStatus } from "@/lib/types";
import { Badge } from "./Badge";

export function Pnl({ value, children, className }: { value: string | number | null | undefined; children: ReactNode; className?: string }) {
  const tone = pnlTone(value);
  return (
    <span className={cn("num", tone === "positive" && "text-positive", tone === "negative" && "text-negative", className)}>
      {children}
    </span>
  );
}

const ENV_TONE = { PAPER: "neutral", DEMO: "info", LIVE: "live", UNKNOWN: "warning" } as const;

export function EnvBadge({ env }: { env: AccountEnvironment }) {
  return (
    <Badge tone={ENV_TONE[env]} className={env === "LIVE" ? "font-bold tracking-wider" : undefined}>
      {env}
    </Badge>
  );
}

const CONN = {
  CONNECTED: { tone: "positive", label: "Connected" },
  DISCONNECTED: { tone: "neutral", label: "Disconnected" },
  RECONNECTING: { tone: "warning", label: "Reconnecting" },
  ERROR: { tone: "negative", label: "Error" },
} as const;

const DOT_TONE = { CONNECTED: "bg-positive", DISCONNECTED: "bg-fg-subtle", RECONNECTING: "bg-warning", ERROR: "bg-negative" } as const;

/** Small status dot with an accessible label. */
export function ConnectionDot({ status }: { status: ConnectionStatus }) {
  return (
    <span className="relative flex size-2.5 shrink-0" role="img" aria-label={CONN[status].label}>
      {status === "CONNECTED" && <span className="absolute inline-flex size-full animate-ping rounded-full bg-positive opacity-30" />}
      <span className={cn("relative inline-flex size-2.5 rounded-full", DOT_TONE[status])} />
    </span>
  );
}

export function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  const c = CONN[status];
  return (
    <Badge tone={c.tone} dot>
      {c.label}
    </Badge>
  );
}

type NoticeTone = "info" | "warning" | "danger" | "success";
const NOTICE = {
  info: { icon: Info, cls: "border-info/30 bg-info-soft text-info" },
  warning: { icon: AlertTriangle, cls: "border-warning/30 bg-warning-soft text-warning" },
  danger: { icon: OctagonAlert, cls: "border-negative/30 bg-negative-soft text-negative" },
  success: { icon: CircleCheck, cls: "border-positive/30 bg-positive-soft text-positive" },
};

export function Notice({ tone = "info", title, children, className }: { tone?: NoticeTone; title?: ReactNode; children?: ReactNode; className?: string }) {
  const { icon: Icon, cls } = NOTICE[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex gap-3 rounded-lg border px-4 py-3 text-sm", cls, className)}>
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cn("text-fg-muted", Boolean(title) && "mt-0.5")}>{children}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, children, action }: { icon: typeof Info; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-3 flex size-10 items-center justify-center rounded-lg border border-line bg-surface-raised">
        <Icon aria-hidden className="size-5 text-fg-muted" />
      </div>
      <p className="text-sm font-semibold text-fg">{title}</p>
      {children && <div className="mt-1.5 max-w-md text-sm leading-relaxed text-fg-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/** Horizontal usage meter: used vs limit, warning from 70 %, danger from 90 %. */
export function Meter({ label, used, limit, detail }: { label: ReactNode; used: number | null; limit: number | null; detail?: ReactNode }) {
  const pct = used !== null && limit ? Math.min(100, (used / limit) * 100) : null;
  const tone = pct === null ? "bg-line-strong" : pct >= 90 ? "bg-negative" : pct >= 70 ? "bg-warning" : "bg-positive";
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="text-fg">{label}</span>
        <span className="num text-xs text-fg-muted">{detail}</span>
      </div>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-raised"
        role="meter"
        aria-valuenow={pct ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={typeof label === "string" ? label : undefined}
      >
        <div className={cn("h-full rounded-full transition-all", tone)} style={{ width: `${pct ?? 0}%` }} />
      </div>
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-y divide-line">
      {items.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-4 py-2 text-sm">
          <dt className="text-fg-muted">{k}</dt>
          <dd className="text-right text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-fg-subtle" role="status">
      <span className="size-3 animate-spin rounded-full border-2 border-line-strong border-t-accent" aria-hidden />
      {label}
    </div>
  );
}

export function SideBadge({ side }: { side: "BUY" | "SELL" }) {
  return <span className={cn("text-xs font-semibold", side === "BUY" ? "text-positive" : "text-negative")}>{side}</span>;
}
