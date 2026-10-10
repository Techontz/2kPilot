import { describe, expect, it } from "vitest";
import { availableFamilies, contractProblems, contractSummary, directionLabel, durationAllowed, initialContract, parseDuration, sizeText, specForFamily } from "./contracts";
import type { ContractOffer } from "./types";

const offer: ContractOffer = {
  account: { id: "a", label: "Deriv demo", environment: "DEMO" },
  provider: "Deriv",
  symbol: "R_75",
  simulated: false,
  market_open: true,
  trading_suspended: false,
  families: {
    RISE_FALL: { available: true, contract_types: ["CALL", "PUT"], allow_equals: false, durations: [{ expiry_type: "tick", min: "1t", max: "10t" }, { expiry_type: "intraday", min: "15s", max: "1d" }] },
    MULTIPLIER: { available: true, contract_types: ["MULTUP", "MULTDOWN"], multipliers: [50, 100, 200] },
    SPOT: { available: false },
  },
  default_contract: specForFamily("RISE_FALL", { duration: 5, duration_unit: "m" }),
  notes: [],
};

describe("contracts", () => {
  it("parses Deriv duration strings and checks ranges", () => {
    expect(parseDuration("15s")).toEqual([15, "s"]);
    expect(parseDuration("1d")).toEqual([1, "d"]);
    expect(parseDuration("x")).toBeNull();
    const ranges = offer.families.RISE_FALL.durations;
    expect(durationAllowed(25, "m", ranges)).toBe(true);
    expect(durationAllowed(5, "s", ranges)).toBe(false);
    expect(durationAllowed(5, "t", ranges)).toBe(true);
    expect(durationAllowed(2, "d", ranges)).toBe(false);
  });

  it("lists the families a symbol offers; Deriv never trades Spot", () => {
    expect(availableFamilies(offer, true)).toEqual(["RISE_FALL", "MULTIPLIER"]);
    expect(availableFamilies(null, false)).toContain("SPOT");
    expect(availableFamilies(null, true)).not.toContain("SPOT");
  });

  it("starts from the strategy's suggestion when the symbol offers it", () => {
    expect(initialContract({ contract_family: "RISE_FALL", duration: 25, duration_unit: "m" }, offer, true)).toMatchObject({ contract_family: "RISE_FALL", duration: 25, duration_unit: "m", multiplier: null });
    // Spot suggested on Deriv → the broker default (Rise/Fall 5 minutes).
    expect(initialContract({ contract_family: "SPOT" }, offer, true)).toMatchObject({ contract_family: "RISE_FALL", duration: 5 });
    // A multiplier the symbol doesn't offer → the first offered one.
    expect(initialContract({ contract_family: "MULTIPLIER", multiplier: 7 }, offer, true)).toMatchObject({ multiplier: 50 });
  });

  it("explains invalid contracts in plain words", () => {
    expect(contractProblems(specForFamily("RISE_FALL", { duration: 5, duration_unit: "s" }), offer, { isDeriv: true }).duration).toMatch(/Not offered/);
    expect(contractProblems(specForFamily("MULTIPLIER", { multiplier: 100, stake: "2", stop_loss_amount: "3" }), offer, { isDeriv: true }).stop_loss_amount).toMatch(/more than the stake/);
    expect(contractProblems(specForFamily("RISE_FALL", { stake: "9" }), offer, { isDeriv: true, maxStake: 5 }).stake).toMatch(/at most 5/);
    expect(contractProblems(specForFamily("SPOT"), offer, { isDeriv: true }).contract_family).toBeDefined();
    expect(contractProblems(specForFamily("RISE_FALL", { duration: 25, duration_unit: "m" }), offer, { isDeriv: true })).toEqual({});
  });

  it("summarises a contract for beginners", () => {
    expect(contractSummary(specForFamily("RISE_FALL", { duration: 25, duration_unit: "m" }), { currency: "USD", profileStake: "1.00" })).toBe("Rise/Fall · 25 minutes · stake $1.00 (risk profile)");
    expect(contractSummary(specForFamily("MULTIPLIER", { multiplier: 100, stake: "2" }), { currency: "USD" })).toBe("Multiplier · ×100 · stake $2.00");
    expect(contractSummary(specForFamily("SPOT"))).toBe("Spot · sized by your risk per trade");
  });

  it("names directions and sizes", () => {
    expect(directionLabel({ side: "BUY", contract_family: "RISE_FALL", contract_type: "CALL" })).toBe("Rise");
    expect(directionLabel({ side: "SELL", contract_family: "RISE_FALL", contract_type: "PUT" })).toBe("Fall");
    expect(directionLabel({ side: "SELL", contract_family: "MULTIPLIER", contract_type: "MULTDOWN" })).toBe("Down");
    expect(directionLabel({ side: "BUY", contract_family: null, contract_type: null })).toBe("Buy");
    expect(sizeText({ stake: "1.5", volume: "1", contract_family: "RISE_FALL" }, "USD")).toBe("$1.50");
    expect(sizeText({ stake: null, volume: "0.10", contract_family: "SPOT" })).toBe("0.1 lots");
  });
});

import { humanDuration, rangesText } from "./contracts";

describe("duration text", () => {
  it("turns broker duration strings into words", () => {
    expect(humanDuration("900s")).toBe("15 minutes");
    expect(humanDuration("1t")).toBe("1 tick");
    expect(humanDuration("86400s")).toBe("1 day");
    expect(rangesText([{ min: "1t", max: "10t" }, { min: "15s", max: "365d" }])).toBe("1 tick – 10 ticks, 15 seconds – 365 days");
  });
});
