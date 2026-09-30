import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "danger-outline";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-canvas hover:bg-accent-strong",
  secondary: "border border-line-strong bg-surface-raised text-fg hover:bg-surface-hover",
  ghost: "text-fg-muted hover:bg-surface-raised hover:text-fg",
  danger: "bg-negative text-white hover:bg-negative/90",
  "danger-outline": "border border-negative/60 text-negative hover:bg-negative-soft",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
}

export function Button({ variant = "secondary", size = "md", className, type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4 text-sm",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}
