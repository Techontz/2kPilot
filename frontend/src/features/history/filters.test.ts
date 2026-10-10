import { describe, expect, it } from "vitest";
import { detectPreset, EMPTY_FILTERS, exportUrl, historyQuery, presetRange, rangeProblem } from "./filters";

const NOW = new Date("2026-10-10T15:30:00Z");

describe("history filters", () => {
  it("leaves empty filters out of the query", () => {
    expect(historyQuery(EMPTY_FILTERS)).toEqual({});
    expect(historyQuery(EMPTY_FILTERS, { page: 2, per_page: 50 })).toEqual({ page: 2, per_page: 50 });
  });

  it("maps every filter to the API parameter", () => {
    const q = historyQuery({ from: "2026-10-01", to: "2026-10-10", accountId: "acc-1", strategyId: "str-9", outcome: "loss" });
    expect(q).toEqual({ account_id: "acc-1", strategy_id: "str-9", from: "2026-10-01", to: "2026-10-10", outcome: "loss" });
  });

  it("ignores malformed dates", () => {
    expect(historyQuery({ ...EMPTY_FILTERS, from: "10/01/2026", to: "yesterday" })).toEqual({});
  });

  it("builds the CSV export URL with the current filters", () => {
    expect(exportUrl(EMPTY_FILTERS)).toBe("/api/history/export?format=csv");
    const url = exportUrl({ from: "2026-10-01", to: "", accountId: "a b", strategyId: "", outcome: "win" });
    expect(url).toBe("/api/history/export?format=csv&account_id=a+b&from=2026-10-01&outcome=win");
    const params = new URL(url, "http://x").searchParams;
    expect(params.get("format")).toBe("csv");
    expect(params.get("account_id")).toBe("a b");
  });

  it("computes preset ranges in UTC days", () => {
    expect(presetRange("today", NOW)).toEqual({ from: "2026-10-10", to: "2026-10-10" });
    expect(presetRange("7d", NOW)).toEqual({ from: "2026-10-04", to: "2026-10-10" });
    expect(presetRange("30d", NOW)).toEqual({ from: "2026-09-11", to: "2026-10-10" });
    expect(presetRange("all", NOW)).toEqual({ from: "", to: "" });
  });

  it("recognises presets and custom ranges", () => {
    expect(detectPreset({ from: "2026-10-04", to: "2026-10-10" }, NOW)).toBe("7d");
    expect(detectPreset({ from: "", to: "" }, NOW)).toBe("all");
    expect(detectPreset({ from: "2026-01-01", to: "2026-02-01" }, NOW)).toBe("custom");
  });

  it("flags an inverted range", () => {
    expect(rangeProblem({ from: "2026-10-10", to: "2026-10-01" })).toMatch(/after/);
    expect(rangeProblem({ from: "2026-10-01", to: "2026-10-10" })).toBeNull();
  });
});
