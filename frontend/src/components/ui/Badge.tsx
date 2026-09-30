import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { Tone } from "@/lib/status";

const TONES: Record<Tone, string> = {
  positive: "bg-positive-soft text-positive",
  negative: "bg-negative-soft text-negative",
  warning: "bg-warning-soft text-warning",
  info: "bg-info-soft text-info",
  neutral: "bg-surface-raised text-fg-muted",
  live: "bg-live text-white",
};

const DOTS: Record<Tone, string> = {
  positive: "bg-positive",
  negative: "bg-negative",
  warning: "bg-warning",
  info: "bg-info",
  neutral: "bg-fg-subtle",
  live: "bg-white",
};

interface BadgeProps {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}

export function Badge({ tone = "neutral", children, dot = false, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {dot && <span aria-hidden className={cn("size-1.5 rounded-full", DOTS[tone])} />}
      {children}
    </span>
  );
}
