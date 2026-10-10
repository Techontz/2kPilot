import { describe, expect, it } from "vitest";
import { toPnlRows, toSeries, zeroAnchoredDomain } from "./series";

describe("toSeries", () => {
  it("sorts out duplicates, drops bad rows and keeps the latest value per second", () => {
    const rows = [
      { t: "2026-01-01T00:00:00Z", v: 1 },
      { t: "2026-01-01T00:00:00Z", v: 2 },
      { t: "garbage", v: 3 },
      { t: "2026-01-01T00:01:00Z", v: null },
      { t: "2026-01-01T00:02:00Z", v: 5 },
    ];
    expect(toSeries(rows, (r) => r.t, (r) => r.v)).toEqual([
      { time: 1767225600, value: 2 },
      { time: 1767225720, value: 5 },
    ]);
  });
});

describe("P/L helpers", () => {
  it("marks each bar's sign", () => {
    expect(toPnlRows([{ label: "a", value: -1 }, { label: "b", value: 0 }]).map((r) => r.positive)).toEqual([false, true]);
  });
  it("always includes the zero baseline", () => {
    expect(zeroAnchoredDomain([5, 10])).toEqual([0, 10]);
    expect(zeroAnchoredDomain([-3, 4])).toEqual([-3, 4]);
    expect(zeroAnchoredDomain([])).toEqual([0, 1]);
  });
});
