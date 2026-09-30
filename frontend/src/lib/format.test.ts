import { describe, expect, it } from "vitest";
import { formatMoney, formatPct, formatPnl, formatPrice, humanize, pnlTone } from "./format";

describe("money and P/L formatting", () => {
  it("never invents numbers for missing values", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatPnl(undefined)).toBe("—");
    expect(formatPct("")).toBe("—");
    expect(formatPrice("not-a-number")).toBe("—");
  });

  it("signs P/L with a true minus", () => {
    expect(formatPnl("12.5")).toBe("+12.50");
    expect(formatPnl(-3.2)).toBe("−3.20");
    expect(formatPnl(0)).toBe("0.00");
  });

  it("uses symbol precision for prices", () => {
    expect(formatPrice("1.085", "EURUSD")).toBe("1.08500");
    expect(formatPrice("151.7", "USDJPY")).toBe("151.700");
  });

  it("classifies P/L tone", () => {
    expect(pnlTone("1")).toBe("positive");
    expect(pnlTone(-1)).toBe("negative");
    expect(pnlTone(null)).toBe("neutral");
  });

  it("humanizes enum keys", () => {
    expect(humanize("NEW_YORK")).toBe("New york");
    expect(formatPct(12.345, 1, true)).toBe("+12.3%");
  });
});
