"use client";

import { Eye, EyeOff } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type InputProps = Omit<React.ComponentProps<"input">, "type" | "id">;

/**
 * Password input with a show/hide toggle. The <label> points at the input by
 * id (the toggle sits outside it, so it never becomes part of the field's
 * name); the hint and error are linked with aria-describedby.
 */
export function PasswordField({ label, hint, error, className, ...input }: InputProps & { label: ReactNode; hint?: ReactNode; error?: string | null }) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const described = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("grid gap-1.5 text-sm", className)}>
      <label htmlFor={id} className="font-semibold text-fg">{label}</label>
      <div className="relative">
        <Input id={id} type={visible ? "text" : "password"} aria-invalid={error ? true : undefined} aria-describedby={described} className="pr-11" {...input} />
        <button type="button" onClick={() => setVisible((v) => !v)} aria-pressed={visible}
          className="absolute top-1/2 right-1 flex size-8 -translate-y-1/2 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg">
          {visible ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
          <span className="sr-only">{visible ? "Hide password" : "Show password"}</span>
        </button>
      </div>
      {hint && !error && <span id={`${id}-hint`} className="text-xs text-fg-subtle">{hint}</span>}
      {error && (
        <span id={`${id}-error`} role="alert" className="flex items-start gap-1.5 text-xs font-medium text-negative">
          <span aria-hidden className="mt-[3px] size-1.5 shrink-0 rounded-full bg-negative" />{error}
        </span>
      )}
    </div>
  );
}
