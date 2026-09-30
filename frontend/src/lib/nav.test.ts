import { describe, expect, it } from "vitest";
import { isActive, NAVIGATION } from "./nav";

describe("navigation", () => {
  it("contains every required section exactly once", () => {
    const labels = NAVIGATION.flatMap((g) => g.items.map((i) => i.label));
    expect(new Set(labels).size).toBe(labels.length);
    expect(labels).toEqual(
      expect.arrayContaining([
        "Overview", "Markets", "Strategies", "Backtesting", "Trading", "Positions", "Orders",
        "Trade History", "Brokers", "Analytics", "Risk Management", "Journal", "Notifications", "Settings",
      ]),
    );
  });

  it("matches active routes", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/risk", "/")).toBe(false);
    expect(isActive("/strategies/abc", "/strategies")).toBe(true);
  });
});
