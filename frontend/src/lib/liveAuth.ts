/**
 * Real-money (LIVE) authorisation — the pure step logic behind
 * features/settings/RealMoneyDialog. Mirrors the server's refusals in
 * backend/app/Services/Trading/TradingControl.php (setMode / modeRefusal) so the
 * dialog explains a blocker before the user ever submits.
 */

import { formatCurrency } from "./format";
import type { Account, RiskProfile, TradingMode } from "./types";

export type LiveAuthStep = "prepare" | "account" | "limits" | "warning" | "credentials" | "done";

export const LIVE_AUTH_STEPS: { step: LiveAuthStep; label: string }[] = [
  { step: "prepare", label: "Get ready" },
  { step: "account", label: "Account" },
  { step: "limits", label: "Limits" },
  { step: "warning", label: "Risk" },
  { step: "credentials", label: "Confirm" },
  { step: "done", label: "Done" },
];

/** Used when GET /trading/status does not (yet) carry `live_confirmation_phrase`. */
export const DEFAULT_LIVE_PHRASE = "ENABLE LIVE TRADING";

export interface LiveAuthContext {
  /** Server lock: LIVE_TRADING_ENABLED=false. */
  locked: boolean;
  /** The user's trading is running (kill switch released): the mode cannot change. */
  running: boolean;
  mode: TradingMode;
  mfaEnabled: boolean;
  /** The user's accounts (only LIVE ones are eligible). */
  accounts: Pick<Account, "id" | "environment" | "risk_profile">[];
  accountId: string | null;
  acknowledged: boolean;
  mfaCode: string;
  password: string;
  phrase: string;
  requiredPhrase: string;
}

export interface LiveAuthBlocker {
  code: "live_locked" | "stop_first" | "already_live" | "no_live_account" | "risk_profile_required" | "mfa_required";
  message: string;
}

export function liveAccounts<T extends Pick<Account, "environment">>(accounts: T[]): T[] {
  return accounts.filter((a) => a.environment === "LIVE");
}

export function selectedAccount(ctx: Pick<LiveAuthContext, "accounts" | "accountId">) {
  return liveAccounts(ctx.accounts).find((a) => a.id === ctx.accountId) ?? null;
}

/** Where the dialog opens: the "get ready" step whenever something must happen first. */
export function firstStep(ctx: Pick<LiveAuthContext, "locked" | "running" | "mode">): LiveAuthStep {
  return ctx.locked || ctx.running || ctx.mode === "LIVE" ? "prepare" : "account";
}

/** What stops the user on a step (null = nothing). Checked in the same order as the server. */
export function blockerFor(step: LiveAuthStep, ctx: LiveAuthContext): LiveAuthBlocker | null {
  switch (step) {
    case "prepare":
      if (ctx.locked) {
        return { code: "live_locked", message: "Real-money trading is locked on this server. The server administrator must enable it (LIVE_TRADING_ENABLED)." };
      }
      if (ctx.mode === "LIVE") return { code: "already_live", message: "LIVE mode is already on." };
      if (ctx.running) {
        return { code: "stop_first", message: "Stop trading first. The mode can only change while trading is stopped." };
      }
      return null;
    case "account":
      if (liveAccounts(ctx.accounts).length === 0) {
        return { code: "no_live_account", message: "You have no LIVE (real-money) account yet. Add your Deriv real account in Settings → Brokers first." };
      }
      return null;
    case "limits": {
      const account = selectedAccount(ctx);
      if (account && !account.risk_profile) {
        return { code: "risk_profile_required", message: "This account has no risk profile. Assign one in Settings → Accounts before trading real money." };
      }
      return null;
    }
    case "credentials":
      if (!ctx.mfaEnabled) {
        return { code: "mfa_required", message: "Set up two-factor authentication first. Real-money trading needs a code from your authenticator app." };
      }
      return null;
    default:
      return null;
  }
}

/** Exact match (surrounding spaces ignored, as on the server). Case matters. */
export function phraseMatches(typed: string, required: string): boolean {
  return typed.trim() === required;
}

export function isMfaCode(code: string): boolean {
  return /^\d{6}$/.test(code.trim());
}

/** May the user press Continue (or, on the last input step, submit)? */
export function canAdvance(step: LiveAuthStep, ctx: LiveAuthContext): boolean {
  if (blockerFor(step, ctx)) return false;
  switch (step) {
    case "prepare":
      return true;
    case "account":
      return selectedAccount(ctx) !== null;
    case "limits":
      return selectedAccount(ctx)?.risk_profile != null;
    case "warning":
      return ctx.acknowledged;
    case "credentials":
      return isMfaCode(ctx.mfaCode) && ctx.password.length > 0 && phraseMatches(ctx.phrase, ctx.requiredPhrase);
    case "done":
      return false;
  }
}

const ORDER: LiveAuthStep[] = LIVE_AUTH_STEPS.map((s) => s.step);

export function nextStep(step: LiveAuthStep): LiveAuthStep {
  return ORDER[Math.min(ORDER.indexOf(step) + 1, ORDER.length - 1)]!;
}

export function previousStep(step: LiveAuthStep): LiveAuthStep {
  return ORDER[Math.max(ORDER.indexOf(step) - 1, 0)]!;
}

export function stepIndex(step: LiveAuthStep): number {
  return ORDER.indexOf(step);
}

export type LiveAuthField = "mfa_code" | "password" | "phrase";

/** Where a refusal from PUT /trading/mode belongs, and in plain words. */
export function errorStep(code: string): { step: LiveAuthStep; field: LiveAuthField | null; message: string } {
  switch (code) {
    case "stop_first":
      return { step: "prepare", field: null, message: "Your trading is running. Stop trading first — the mode can only change while trading is stopped." };
    case "live_locked":
      return { step: "prepare", field: null, message: "Real-money trading is locked on this server. The server administrator must enable it (LIVE_TRADING_ENABLED)." };
    case "live_account_required":
      return { step: "account", field: null, message: "Choose one of your LIVE accounts." };
    case "risk_profile_required":
      return { step: "limits", field: null, message: "That account needs a risk profile before it can trade real money. Assign one in Settings → Accounts." };
    case "mfa_required":
      return { step: "credentials", field: null, message: "Set up two-factor authentication first." };
    case "mfa_code_invalid":
      return { step: "credentials", field: "mfa_code", message: "That code is not valid. Enter the current 6-digit code from your authenticator app." };
    case "password_incorrect":
      return { step: "credentials", field: "password", message: "That password is not correct." };
    case "confirmation_required":
      return { step: "credentials", field: "phrase", message: "Type the confirmation phrase exactly as shown." };
    default:
      return { step: "credentials", field: null, message: "LIVE mode was not turned on. Try again." };
  }
}

export interface LimitSentence {
  key: string;
  text: string;
  /** "warning" = this optional limit is off. */
  tone: "ok" | "warning";
}

function num(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

const NO_LIMIT = "No limit set";

/** A risk profile's contract limits, in plain words, for the authorisation step. */
export function limitSentences(
  profile: Pick<RiskProfile, "stake_amount" | "max_stake_amount" | "max_consecutive_losses" | "max_daily_loss_amount" | "max_daily_loss_pct" | "daily_profit_target_amount" | "max_trades_per_day" | "max_open_positions">,
  currency?: string | null,
): LimitSentence[] {
  const money = (v: string | number) => formatCurrency(v, currency);
  const out: LimitSentence[] = [];
  const stake = num(profile.stake_amount);
  out.push(stake !== null
    ? { key: "stake", text: `Each trade risks ${money(stake)} (stake per trade)`, tone: "ok" }
    : { key: "stake", text: `Stake per trade: ${NO_LIMIT}`, tone: "warning" });

  const maxStake = num(profile.max_stake_amount);
  out.push(maxStake !== null
    ? { key: "max_stake", text: `Never more than ${money(maxStake)} on one trade`, tone: "ok" }
    : { key: "max_stake", text: `Largest stake on one trade: ${NO_LIMIT}`, tone: "warning" });

  const streak = num(profile.max_consecutive_losses);
  out.push(streak !== null
    ? { key: "streak", text: `Stops for the day after ${streak} ${streak === 1 ? "loss" : "losses"} in a row`, tone: "ok" }
    : { key: "streak", text: `Losses in a row: ${NO_LIMIT}`, tone: "warning" });

  const lossAmount = num(profile.max_daily_loss_amount);
  const lossPct = num(profile.max_daily_loss_pct);
  if (lossAmount !== null) out.push({ key: "daily_loss_amount", text: `Stops for the day after losing ${money(lossAmount)}`, tone: "ok" });
  if (lossPct !== null) out.push({ key: "daily_loss_pct", text: `Stops for the day after losing ${lossPct}% of the balance`, tone: "ok" });
  if (lossAmount === null && lossPct === null) out.push({ key: "daily_loss", text: `Daily loss limit: ${NO_LIMIT}`, tone: "warning" });

  const target = num(profile.daily_profit_target_amount);
  out.push(target !== null
    ? { key: "profit_target", text: `Stops for the day after making ${money(target)}`, tone: "ok" }
    : { key: "profit_target", text: `Daily profit target: ${NO_LIMIT}`, tone: "warning" });

  const trades = num(profile.max_trades_per_day);
  out.push(trades !== null
    ? { key: "trades_per_day", text: `At most ${trades} ${trades === 1 ? "trade" : "trades"} a day`, tone: "ok" }
    : { key: "trades_per_day", text: `Trades per day: ${NO_LIMIT}`, tone: "warning" });

  const open = num(profile.max_open_positions);
  out.push(open !== null
    ? { key: "open_positions", text: `At most ${open} open at once`, tone: "ok" }
    : { key: "open_positions", text: `Trades open at once: ${NO_LIMIT}`, tone: "warning" });
  return out;
}
