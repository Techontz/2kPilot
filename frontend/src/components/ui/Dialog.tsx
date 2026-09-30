"use client";

import { X } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";
import { cn } from "@/lib/cn";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg" | "xl";
  variant?: "modal" | "drawer";
}

/** Native <dialog> (focus trap + Esc) used as a centred modal or a right drawer. */
export function Dialog({ open, onClose, title, children, footer, size = "md", variant = "modal" }: DialogProps) {
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

  const width = { md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" }[size];
  return (
    <dialog
      ref={ref}
      aria-label={typeof title === "string" ? title : undefined}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => e.target === ref.current && onClose()}
      className={cn(
        "border border-line-strong bg-surface p-0 text-fg shadow-2xl shadow-black/60",
        variant === "modal"
          ? cn("m-auto w-[calc(100%-2rem)] rounded-xl", width)
          : "ml-auto mr-0 h-full max-h-none w-full max-w-2xl rounded-none sm:rounded-l-xl",
      )}
    >
      {open && (
        <div className={cn("flex flex-col", variant === "drawer" ? "h-full" : "max-h-[85vh]")}>
          <header className="flex items-center justify-between gap-4 border-b border-line px-5 py-4">
            <h2 className="text-base font-semibold">{title}</h2>
            <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1 text-fg-muted hover:bg-surface-raised">
              <X className="size-4" />
            </button>
          </header>
          <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
  );
}
