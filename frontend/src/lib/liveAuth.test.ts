import { describe, expect, it } from "vitest";
import {
  blockerFor,
  canAdvance,
  DEFAULT_LIVE_PHRASE,
  errorStep,
  firstStep,
  isMfaCode,
  limitSentences,
  type LiveAuthContext,
  nextStep,
  phraseMatches,
  previousStep,
} from "./liveAuth";

const LIVE = { id: "live-1", environment: "LIVE" as const, risk_profile: { id: "rp-1", name: "Beginner" } };
const LIVE_NO_PROFILE = { id: "live-2", environment: "LIVE" as const, risk_profile: null };
const DEMO = { id: "demo-1", environment: "DEMO" as const, risk_profile: { id: "rp-1", name: "Beginner" } };

function ctx(overrides: Partial<LiveAuthContext> = {}): LiveAuthContext {
  return {
    locked: false,
    running: false,
    mode: "DEMO",
    mfaEnabled: true,
    accounts: [DEMO, LIVE],
    accountId: "live-1",
    acknowledged: true,
    mfaCode: "123456",
    password: "secret",
    phrase: DEFAULT_LIVE_PHRASE,
    requiredPhrase: DEFAULT_LIVE_PHRASE,
    ...overrides,
  };
}

describe("firstStep", () => {
  it("opens on the account step when nothing is in the way", () => {
    expect(firstStep(ctx())).toBe("account");
  });
  it("opens on the get-ready step when locked, running or already LIVE", () => {
    expect(firstStep(ctx({ locked: true }))).toBe("prepare");
    expect(firstStep(ctx({ running: true }))).toBe("prepare");
    expect(firstStep(ctx({ mode: "LIVE" }))).toBe("prepare");
  });
});

describe("blockers", () => {
  it("a server lock blocks everything, before the running check", () => {
    const c = ctx({ locked: true, running: true });
    expect(blockerFor("prepare", c)?.code).toBe("live_locked");
    expect(blockerFor("prepare", c)?.message).toContain("LIVE_TRADING_ENABLED");
    expect(canAdvance("prepare", c)).toBe(false);
  });
  it("running trading must be stopped first", () => {
    const c = ctx({ running: true });
    expect(blockerFor("prepare", c)?.code).toBe("stop_first");
    expect(canAdvance("prepare", c)).toBe(false);
    expect(canAdvance("prepare", ctx())).toBe(true);
  });
  it("already LIVE has nothing to authorise", () => {
    expect(blockerFor("prepare", ctx({ mode: "LIVE" }))?.code).toBe("already_live");
  });
  it("needs a LIVE account (demo accounts do not count)", () => {
    const c = ctx({ accounts: [DEMO], accountId: null });
    expect(blockerFor("account", c)?.code).toBe("no_live_account");
    expect(canAdvance("account", c)).toBe(false);
  });
  it("needs an account to be chosen, and only a LIVE one", () => {
    expect(canAdvance("account", ctx({ accountId: null }))).toBe(false);
    expect(canAdvance("account", ctx({ accountId: "demo-1" }))).toBe(false);
    expect(canAdvance("account", ctx())).toBe(true);
  });
  it("needs a risk profile on the chosen account", () => {
    const c = ctx({ accounts: [LIVE_NO_PROFILE], accountId: "live-2" });
    expect(blockerFor("limits", c)?.code).toBe("risk_profile_required");
    expect(canAdvance("limits", c)).toBe(false);
    expect(canAdvance("limits", ctx())).toBe(true);
  });
  it("needs two-factor authentication", () => {
    const c = ctx({ mfaEnabled: false });
    expect(blockerFor("credentials", c)?.code).toBe("mfa_required");
    expect(canAdvance("credentials", c)).toBe(false);
  });
});

describe("risk acknowledgement and credentials", () => {
  it("the checkbox is required", () => {
    expect(canAdvance("warning", ctx({ acknowledged: false }))).toBe(false);
    expect(canAdvance("warning", ctx())).toBe(true);
  });
  it("the phrase must match exactly (case matters; outer spaces ignored like the server)", () => {
    expect(phraseMatches("ENABLE LIVE TRADING", DEFAULT_LIVE_PHRASE)).toBe(true);
    expect(phraseMatches("  ENABLE LIVE TRADING ", DEFAULT_LIVE_PHRASE)).toBe(true);
    expect(phraseMatches("enable live trading", DEFAULT_LIVE_PHRASE)).toBe(false);
    expect(phraseMatches("ENABLE LIVE", DEFAULT_LIVE_PHRASE)).toBe(false);
    expect(canAdvance("credentials", ctx({ phrase: "enable live trading" }))).toBe(false);
    expect(canAdvance("credentials", ctx({ requiredPhrase: "TRADE REAL MONEY", phrase: "TRADE REAL MONEY" }))).toBe(true);
  });
  it("needs a 6-digit code and a password", () => {
    expect(isMfaCode("123456")).toBe(true);
    expect(isMfaCode("12345")).toBe(false);
    expect(isMfaCode("12345a")).toBe(false);
    expect(canAdvance("credentials", ctx({ mfaCode: "1234" }))).toBe(false);
    expect(canAdvance("credentials", ctx({ password: "" }))).toBe(false);
    expect(canAdvance("credentials", ctx())).toBe(true);
  });
  it("the done step has nowhere to go", () => {
    expect(canAdvance("done", ctx())).toBe(false);
  });
});

describe("step order", () => {
  it("moves forward and back within bounds", () => {
    expect(nextStep("prepare")).toBe("account");
    expect(nextStep("credentials")).toBe("done");
    expect(nextStep("done")).toBe("done");
    expect(previousStep("account")).toBe("prepare");
    expect(previousStep("prepare")).toBe("prepare");
  });
});

describe("errorStep", () => {
  it.each([
    ["stop_first", "prepare", null],
    ["live_locked", "prepare", null],
    ["live_account_required", "account", null],
    ["risk_profile_required", "limits", null],
    ["mfa_required", "credentials", null],
    ["mfa_code_invalid", "credentials", "mfa_code"],
    ["password_incorrect", "credentials", "password"],
    ["confirmation_required", "credentials", "phrase"],
    ["something_new", "credentials", null],
  ])("%s → %s (%s)", (code, step, field) => {
    const result = errorStep(code);
    expect(result.step).toBe(step);
    expect(result.field).toBe(field);
    expect(result.message.length).toBeGreaterThan(5);
  });
});

describe("limitSentences", () => {
  const full = {
    stake_amount: "1.00",
    max_stake_amount: "5.00",
    max_consecutive_losses: 3,
    max_daily_loss_amount: "20.00",
    max_daily_loss_pct: "2.000",
    daily_profit_target_amount: "10.00",
    max_trades_per_day: 20,
    max_open_positions: 1,
  };

  it("puts every limit in plain words with the account currency", () => {
    const texts = limitSentences(full, "USD").map((s) => s.text);
    expect(texts).toEqual([
      "Each trade risks $1.00 (stake per trade)",
      "Never more than $5.00 on one trade",
      "Stops for the day after 3 losses in a row",
      "Stops for the day after losing $20.00",
      "Stops for the day after losing 2% of the balance",
      "Stops for the day after making $10.00",
      "At most 20 trades a day",
      "At most 1 open at once",
    ]);
    expect(limitSentences(full, "USD").every((s) => s.tone === "ok")).toBe(true);
  });

  it("shows missing optional limits as 'No limit set' in warning tone", () => {
    const sentences = limitSentences({
      ...full,
      max_stake_amount: null,
      max_consecutive_losses: null,
      max_daily_loss_amount: null,
      max_daily_loss_pct: null,
      daily_profit_target_amount: null,
      max_trades_per_day: null,
      max_open_positions: null,
    }, "USD");
    expect(sentences[0]).toMatchObject({ tone: "ok", text: "Each trade risks $1.00 (stake per trade)" });
    const missing = sentences.slice(1);
    expect(missing).toHaveLength(6);
    for (const s of missing) {
      expect(s.tone).toBe("warning");
      expect(s.text).toContain("No limit set");
    }
  });

  it("uses only the daily loss limit that is set", () => {
    const amountOnly = limitSentences({ ...full, max_daily_loss_pct: null }, "USD").map((s) => s.key);
    expect(amountOnly).toContain("daily_loss_amount");
    expect(amountOnly).not.toContain("daily_loss_pct");
    const pctOnly = limitSentences({ ...full, max_daily_loss_amount: null }, "USD").map((s) => s.text);
    expect(pctOnly).toContain("Stops for the day after losing 2% of the balance");
  });

  it("uses singular words for one", () => {
    const texts = limitSentences({ ...full, max_consecutive_losses: 1, max_trades_per_day: 1 }, "USD").map((s) => s.text);
    expect(texts).toContain("Stops for the day after 1 loss in a row");
    expect(texts).toContain("At most 1 trade a day");
  });
});
