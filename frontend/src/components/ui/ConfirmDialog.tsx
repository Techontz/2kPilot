"use client";

import { type ReactNode, useEffect, useRef } from "react";
import { Button } from "./Button";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  confirmVariant?: "primary" | "danger";
  busy?: boolean;
  confirmDisabled?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Native <dialog> for focus trapping and Esc handling without extra dependencies. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  confirmVariant = "primary",
  busy = false,
  confirmDisabled = false,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onCancel();
      }}
      className="m-auto w-full max-w-md rounded-xl border border-line-strong bg-surface p-0 text-fg shadow-2xl shadow-black/60"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onConfirm();
        }}
      >
        <div className="px-6 pt-5 pb-4">
          <h2 id="confirm-dialog-title" className="text-base font-semibold">
            {title}
          </h2>
          <div className="mt-2 space-y-3 text-sm leading-relaxed text-fg-muted">{children}</div>
          {error && (
            <p role="alert" className="mt-3 rounded-lg bg-negative-soft px-3 py-2 text-sm text-negative">
              {error}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-line px-6 py-4">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant={confirmVariant} disabled={busy || confirmDisabled}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
