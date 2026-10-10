import { describe, expect, it } from "vitest";
import { DRAFT_STORAGE_KEY, readDraft, storeDraft } from "./draft";

function memory() {
  const data = new Map<string, string>();
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v), data };
}

const rules = { schema_version: 1 as const, timeframe: "M5" as const, entry: { buy: { all: [] } } };

describe("draft storage", () => {
  it("round-trips a draft", () => {
    const s = memory();
    expect(storeDraft({ rules, explanation: "E", warnings: ["w"], unsupported: ["u"], source: "ai", name: "N" }, s)).toBe(true);
    expect(s.data.has(DRAFT_STORAGE_KEY)).toBe(true);
    expect(readDraft(s)).toEqual({ rules, explanation: "E", warnings: ["w"], unsupported: ["u"], source: "ai", name: "N", description: undefined });
  });

  it("ignores missing, broken or rule-less drafts", () => {
    const s = memory();
    expect(readDraft(s)).toBeNull();
    s.setItem(DRAFT_STORAGE_KEY, "{not json");
    expect(readDraft(s)).toBeNull();
    s.setItem(DRAFT_STORAGE_KEY, JSON.stringify({ rules: null, explanation: "x" }));
    expect(readDraft(s)).toBeNull();
    expect(readDraft(undefined)).toBeNull();
  });

  it("normalises optional fields", () => {
    const s = memory();
    s.setItem(DRAFT_STORAGE_KEY, JSON.stringify({ rules, warnings: "nope" }));
    expect(readDraft(s)).toMatchObject({ explanation: "", warnings: [], unsupported: [] });
  });

  it("reports storage failures", () => {
    expect(storeDraft({ rules, explanation: "", warnings: [], unsupported: [], source: "ai" }, { setItem: () => { throw new Error("full"); } })).toBe(false);
  });
});
