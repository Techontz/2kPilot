"use client";

import { useId, useState } from "react";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

interface TermProps {
  id: GlossaryKey;
  /** Visible text; defaults to the glossary term. */
  children?: React.ReactNode;
}

/**
 * Inline glossary term: dotted underline, definition on hover or keyboard
 * focus. Progressive disclosure — beginners get help, experts are not slowed down.
 */
export function Term({ id, children }: TermProps) {
  const entry = GLOSSARY[id];
  const tooltipId = useId();
  const [open, setOpen] = useState(false);

  return (
    <span className="relative inline-block">
      <button
        type="button"
        aria-describedby={open ? tooltipId : undefined}
        className="cursor-help border-b border-dotted border-fg-subtle text-left leading-tight"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      >
        {children ?? entry.term}
      </button>
      {open && (
        <span
          role="tooltip"
          id={tooltipId}
          className="absolute top-full left-0 z-50 mt-2 w-72 rounded-lg border border-line-strong bg-surface-raised p-3 text-left text-xs leading-relaxed font-normal normal-case tracking-normal text-fg-muted shadow-xl shadow-black/40"
        >
          <span className="mb-1 block font-semibold text-fg">{entry.term}</span>
          {entry.definition}
          {"why" in entry && entry.why && <span className="mt-1.5 block text-fg-subtle">{entry.why}</span>}
        </span>
      )}
    </span>
  );
}
