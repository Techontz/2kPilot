import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface StatCardProps {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  valueClassName?: string;
}

/** A single KPI. Shows "—" rather than an invented number when data is missing. */
export function StatCard({ label, value, hint, valueClassName }: StatCardProps) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3.5">
      <div className="text-xs font-medium tracking-wide text-fg-muted uppercase">{label}</div>
      <div className={cn("num mt-2 text-xl font-semibold text-fg", valueClassName)}>{value}</div>
      {hint && <div className="mt-1 text-xs text-fg-subtle">{hint}</div>}
    </div>
  );
}
