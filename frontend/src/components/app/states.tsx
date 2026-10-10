import { AlertTriangle, CircleCheck, Info, type LucideIcon, OctagonAlert, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type NoticeTone = "info" | "warning" | "danger" | "success" | "live";

const NOTICE: Record<NoticeTone, { icon: LucideIcon; cls: string }> = {
  info: { icon: Info, cls: "border-line bg-surface-raised [&_[data-slot=notice-icon]]:text-brand-ink" },
  warning: { icon: AlertTriangle, cls: "border-warning/30 bg-warning-soft [&_[data-slot=notice-icon]]:text-warning" },
  danger: { icon: OctagonAlert, cls: "border-negative/30 bg-negative-soft [&_[data-slot=notice-icon]]:text-negative" },
  success: { icon: CircleCheck, cls: "border-positive/30 bg-positive-soft [&_[data-slot=notice-icon]]:text-positive" },
  live: { icon: OctagonAlert, cls: "border-live/40 bg-live-soft [&_[data-slot=notice-icon]]:text-live" },
};

/** Inline message box. Danger is announced (role=alert); the rest are polite status. */
export function Notice({ tone = "info", title, children, action, className }: { tone?: NoticeTone; title?: ReactNode; children?: ReactNode; action?: ReactNode; className?: string }) {
  const { icon: Icon, cls } = NOTICE[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex gap-3 rounded-lg border px-4 py-3.5 text-sm text-fg", cls, className)}>
      <Icon data-slot="notice-icon" aria-hidden className="mt-0.5 size-[18px] shrink-0" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-bold text-fg">{title}</p>}
        {children && <div className={cn("text-fg-muted", Boolean(title) && "mt-0.5")}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}

/** Nothing here yet — always with the next action. */
export function EmptyState({ icon: Icon, title, children, action, className }: { icon: LucideIcon; title: string; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center px-6 py-10 text-center", className)}>
      <EmptyArt icon={Icon} />
      <p className="text-base font-bold tracking-tight text-fg">{title}</p>
      {children && <div className="mt-1.5 max-w-md text-sm leading-relaxed text-fg-muted">{children}</div>}
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

/**
 * Small illustration for empty states: two stacked "cards", a dashed flight
 * path and the topic icon on a raised tile. Pure SVG + tokens, so it follows
 * the theme.
 */
function EmptyArt({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <div aria-hidden className="relative mb-4 h-24 w-32">
      <svg viewBox="0 0 128 96" className="absolute inset-0 size-full" fill="none">
        <ellipse cx="64" cy="52" rx="56" ry="38" className="fill-[color-mix(in_oklab,var(--primary)_9%,transparent)]" />
        <rect x="22" y="30" width="46" height="34" rx="7" transform="rotate(-10 45 47)" className="fill-surface-hover stroke-line-strong" strokeWidth="1.5" />
        <rect x="60" y="28" width="46" height="34" rx="7" transform="rotate(9 83 45)" className="fill-surface-hover stroke-line-strong" strokeWidth="1.5" />
        <path d="M10 78c18-2 26-16 40-16s20 10 36 6 22-22 32-34" className="stroke-primary/60" strokeWidth="1.6" strokeDasharray="3 4" strokeLinecap="round" />
        <circle cx="118" cy="34" r="3" className="fill-primary" />
        <circle cx="14" cy="22" r="2" className="fill-fg-subtle/50" />
        <circle cx="104" cy="12" r="1.6" className="fill-fg-subtle/50" />
      </svg>
      <span className="absolute top-1/2 left-1/2 flex size-12 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-xl bg-card shadow-raised ring-1 ring-line">
        <Icon className="size-[22px] text-brand-ink" />
      </span>
    </div>
  );
}

/** Could not load — says what happened and offers a retry. */
export function ErrorState({ message, onRetry, className }: { message: string; onRetry?: () => void; className?: string }) {
  return (
    <Notice
      tone="danger"
      title="Couldn't load this"
      className={className}
      action={onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw aria-hidden /> Retry
        </Button>
      )}
    >
      {message}
    </Notice>
  );
}

/** Placeholder rows while a list loads. */
export function ListSkeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-3", className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-10 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

/** Placeholder cards (grid) while cards load. */
export function CardsSkeleton({ count = 3, className }: { count?: number; className?: string }) {
  return (
    <div className={cn("grid gap-4 md:grid-cols-2 xl:grid-cols-3", className)} role="status" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="space-y-3 rounded-lg bg-card p-4 ring-1 ring-line">
          <Skeleton className="aspect-[16/9] w-full rounded-md" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      ))}
    </div>
  );
}

/** Definition list of label → value rows. */
export function KeyValue({ items, className }: { items: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("divide-y divide-border", className)}>
      {items.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-4 py-2 text-sm">
          <dt className="text-fg-muted">{k}</dt>
          <dd className="min-w-0 text-right text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Section heading inside a tab: title, one-line explanation, actions on the right. */
export function SectionHeader({ title, description, actions, className }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-4 flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        <h2 className="text-xl font-extrabold tracking-tight text-fg sm:text-2xl">{title}</h2>
        {description && <p className="mt-0.5 max-w-2xl text-sm text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
