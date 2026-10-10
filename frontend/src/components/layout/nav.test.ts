import { describe, expect, it } from "vitest";
import { LEGACY_REDIRECTS } from "../../../next.config";
import { isActive, NAVIGATION } from "./nav";

describe("navigation", () => {
  it("has exactly the four sections, in order", () => {
    expect(NAVIGATION.map((n) => [n.label, n.href])).toEqual([
      ["Home", "/"],
      ["Strategies", "/strategies"],
      ["History", "/history"],
      ["Settings", "/settings"],
    ]);
  });

  it("marks nested pages as part of their section", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/history", "/")).toBe(false);
    expect(isActive("/strategies/backtests/abc", "/strategies")).toBe(true);
    expect(isActive("/settings/brokers/new", "/settings")).toBe(true);
    expect(isActive("/settingsx", "/settings")).toBe(false);
  });

  it("sends every legacy URL into one of the four sections", () => {
    const sections = NAVIGATION.map((n) => n.href);
    for (const r of LEGACY_REDIRECTS) {
      const path = r.destination.split("?")[0]!;
      expect(sections.some((s) => isActive(path, s)), `${r.source} → ${r.destination}`).toBe(true);
    }
    const sources = LEGACY_REDIRECTS.map((r) => r.source);
    for (const old of ["/positions", "/orders", "/journal", "/analytics", "/markets", "/trade", "/backtesting", "/backtesting/:id", "/brokers", "/brokers/new", "/risk", "/notifications"]) {
      expect(sources).toContain(old);
    }
  });
});
