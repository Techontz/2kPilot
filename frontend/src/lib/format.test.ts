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

import { formatCountdown, formatCurrency, formatDuration, formatSignedCurrency } from "./format";

describe("account-currency money", () => {
  it("formats money in the account currency", () => {
    expect(formatCurrency("1234.5", "USD")).toBe("$1,234.50");
    expect(formatCurrency(-3, "USD")).toBe("-$3.00");
    expect(formatCurrency(null, "USD")).toBe("—");
    expect(formatCurrency(10, "XXQ")).toMatch(/XXQ.*10\.00/); // unknown codes still show the code
    expect(formatCurrency(10, "usd-ish")).toBe("10.00 usd-ish");
  });

  it("signs P/L with + and a true minus, never −$0.00", () => {
    expect(formatSignedCurrency(12.5, "USD")).toBe("+$12.50");
    expect(formatSignedCurrency("-3.2", "USD")).toBe("−$3.20");
    expect(formatSignedCurrency(0, "USD")).toBe("$0.00");
    expect(formatSignedCurrency(-0.001, "USD")).toBe("$0.00");
    expect(formatSignedCurrency(5, "EUR")).toBe("+€5.00");
  });

  it("formats durations and countdowns", () => {
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(310)).toBe("5m 10s");
    expect(formatDuration(7500)).toBe("2h 5m");
    expect(formatDuration(null)).toBe("—");
    const now = Date.parse("2026-10-10T12:00:00Z");
    expect(formatCountdown("2026-10-10T12:04:59Z", now)).toBe("4:59");
    expect(formatCountdown("2026-10-10T13:02:03Z", now)).toBe("1:02:03");
    expect(formatCountdown("2026-10-10T11:00:00Z", now)).toBe("0:00");
    expect(formatCountdown(null, now)).toBeNull();
  });
});
