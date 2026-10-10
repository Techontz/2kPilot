/**
 * A plain-English draft handed from the "Describe it" dialog to the builder
 * (sessionStorage, this tab only — never saved on the server until the user
 * presses Save in the builder).
 */
import type { RuleSet } from "@/lib/types";

export const DRAFT_STORAGE_KEY = "tp.strategy-draft";

export interface StoredDraft {
  rules: RuleSet;
  name?: string;
  description?: string;
  explanation: string;
  warnings: string[];
  unsupported: string[];
  source: "ai";
}

export function storeDraft(draft: StoredDraft, storage: Pick<Storage, "setItem"> | undefined = typeof window === "undefined" ? undefined : window.sessionStorage): boolean {
  try {
    storage?.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
    return storage !== undefined;
  } catch {
    return false;
  }
}

/** The stored draft, or null when there is none or it isn't usable. */
export function readDraft(storage: Pick<Storage, "getItem"> | undefined = typeof window === "undefined" ? undefined : window.sessionStorage): StoredDraft | null {
  try {
    const raw = storage?.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredDraft> | null;
    if (!parsed || typeof parsed !== "object" || !parsed.rules || typeof parsed.rules !== "object" || !parsed.rules.entry) return null;
    const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : []);
    return {
      rules: parsed.rules,
      name: typeof parsed.name === "string" ? parsed.name : undefined,
      description: typeof parsed.description === "string" ? parsed.description : undefined,
      explanation: typeof parsed.explanation === "string" ? parsed.explanation : "",
      warnings: list(parsed.warnings),
      unsupported: list(parsed.unsupported),
      source: "ai",
    };
  } catch {
    return null;
  }
}
