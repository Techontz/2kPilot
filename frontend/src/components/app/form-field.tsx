import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Label + control + hint/error. The <label> wraps the control, so the input is
 * named by the label without ids (and screen readers announce hint/errors).
 */
export function FormField({ label, hint, error, children, className }: { label: ReactNode; hint?: ReactNode; error?: string | null; children: ReactNode; className?: string }) {
  return (
    <label className={cn("grid gap-1.5 text-sm", className)}>
      <span className="font-semibold text-fg">{label}</span>
      {children}
      {hint && !error && <span className="text-xs text-fg-subtle">{hint}</span>}
      {error && <span role="alert" className="flex items-start gap-1.5 text-xs font-medium text-negative"><span aria-hidden className="mt-[3px] size-1.5 shrink-0 rounded-full bg-negative" />{error}</span>}
    </label>
  );
}
