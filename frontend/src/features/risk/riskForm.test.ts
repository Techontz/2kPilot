import { describe, expect, it } from "vitest";
import type { RiskProfile } from "@/lib/types";
import { advancedErrorKeys, ALL_FIELDS, BASIC_FIELDS, toBody, toForm, trimDecimal } from "./riskForm";

const PROFILE = {
  id: "rp-1", name: "Beginner", risk_per_trade_pct: "0.500", max_position_lots: "1.0000", max_open_positions: 3, max_positions_per_symbol: 1,
  max_symbol_exposure_lots: "1.0000", max_total_exposure_lots: "3.0000", max_total_risk_pct: "2.000", max_daily_loss_pct: "2.000",
  max_weekly_loss_pct: "4.000", max_drawdown_pct: "10.000", max_trades_per_day: 20, max_spread_pips: "2.50", max_slippage_pips: "1.50",
  min_stop_pips: "8.00", max_stop_pips: "150.00", min_reward_risk: "1.50", allowed_sessions: ["LONDON"], trading_hours_start: "07:00:00",
  trading_hours_end: "16:00:00", cooldown_after_losses: 3, cooldown_minutes: 240, max_data_age_seconds: 120, stake_amount: "1.00",
  max_stake_amount: "5.00", max_daily_loss_amount: null, max_consecutive_losses: 3, daily_profit_target_amount: null, accounts_count: 0,
} satisfies RiskProfile;

describe("risk profile form", () => {
  it("leads with the stake-based beginner fields, stake first and required", () => {
    expect(BASIC_FIELDS.map((f) => f.key)).toEqual([
      "stake_amount", "max_stake_amount", "max_daily_loss_amount", "max_daily_loss_pct",
      "max_consecutive_losses", "daily_profit_target_amount", "max_trades_per_day", "max_open_positions",
    ]);
    expect(BASIC_FIELDS[0]!.required).toBe(true);
    expect(ALL_FIELDS.filter((f) => f.required).map((f) => f.key).sort()).toEqual(["max_data_age_seconds", "risk_per_trade_pct", "stake_amount"]);
  });

  it("trims decimals for display", () => {
    expect(trimDecimal("2.000")).toBe("2");
    expect(trimDecimal("0.500")).toBe("0.5");
    expect(trimDecimal("150.00")).toBe("150");
    expect(trimDecimal(3)).toBe("3");
    expect(trimDecimal(null)).toBe("");
  });

  it("round-trips a profile; empty optional limits are sent as null (off)", () => {
    const form = toForm(PROFILE);
    expect(form.values.max_daily_loss_amount).toBe("");
    expect(form.hoursStart).toBe("07:00");
    const body = toBody(form);
    expect(body.max_daily_loss_amount).toBeNull();
    expect(body.stake_amount).toBe("1");
    expect(body.max_daily_loss_pct).toBe("2");
    expect(body.allowed_sessions).toEqual(["LONDON"]);
    expect(body.trading_hours_end).toBe("16:00");
  });

  it("starts a new profile from the Beginner limits", () => {
    const form = toForm(null);
    expect(form.name).toBe("");
    expect(form.values.stake_amount).toBe("1");
    expect(form.values.risk_per_trade_pct).toBe("0.5");
    expect(toBody(form).max_daily_loss_amount).toBeNull();
  });

  it("accepts a decimal comma", () => {
    const form = toForm(null);
    form.values.stake_amount = "2,5";
    expect(toBody(form).stake_amount).toBe("2.5");
  });

  it("knows which errors belong to the Advanced section", () => {
    expect(advancedErrorKeys({ stake_amount: ["x"], min_stop_pips: ["y"], "allowed_sessions.0": ["z"] })).toEqual(["min_stop_pips", "allowed_sessions.0"]);
  });
});
