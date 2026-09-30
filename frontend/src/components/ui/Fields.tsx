import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export const inputBase =
  "block h-9 w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none disabled:opacity-60";

interface FieldProps {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  className?: string;
}

export function Field({ label, hint, error, children, className }: FieldProps) {
  return (
    <label className={cn("block text-sm", className)}>
      <span className="mb-1.5 block text-xs font-medium text-fg-muted">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-fg-subtle">{hint}</span>}
      {error && <span className="mt-1 block text-xs text-negative">{error}</span>}
    </label>
  );
}

export function TextInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(inputBase, className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(inputBase, "pr-8", className)} {...props}>
      {children}
    </select>
  );
}

interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
  description?: ReactNode;
}

export function Toggle({ checked, onChange, label, disabled, description }: ToggleProps) {
  return (
    <label className={cn("flex items-start gap-3", disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer")}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors",
          checked ? "bg-accent" : "bg-line-strong",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 size-4 rounded-full bg-white transition-transform",
            checked && "translate-x-4",
          )}
        />
      </button>
      <span className="text-sm">
        <span className="text-fg">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-fg-subtle">{description}</span>}
      </span>
    </label>
  );
}

interface SegmentedProps<T extends string> {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "md";
}

export function Segmented<T extends string>({ value, options, onChange, label, size = "md" }: SegmentedProps<T>) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-md font-medium transition-colors",
            size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm",
            value === o.value ? "bg-surface-raised text-fg" : "text-fg-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
