"use client";

import type { ReactNode } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

/**
 * Inline glossary term: dotted underline, plain-language definition on hover
 * or keyboard focus (shadcn Tooltip). Beginners get help; experts aren't slowed down.
 */
export function Term({ id, children }: { id: GlossaryKey; children?: ReactNode }) {
  const entry = GLOSSARY[id];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="cursor-help border-b border-dotted border-current/50 text-left leading-tight">
          {children ?? entry.term}
        </button>
      </TooltipTrigger>
      <TooltipContent className="block max-w-72 px-3 py-2 text-left leading-relaxed">
        <span className="mb-0.5 block font-semibold">{entry.term}</span>
        {entry.definition}
        {"why" in entry && entry.why && <span className="mt-1 block opacity-80">{entry.why}</span>}
      </TooltipContent>
    </Tooltip>
  );
}
