import type { EngineSummary, EngineSummaryCode, TradingMode, TradingStatus } from "./types";

export type Tone = "positive" | "negative" | "warning" | "neutral" | "live" | "info";

export interface RobotStatus {
  label: string;
  tone: Tone;
  detail: string;
  running: boolean;
}

export interface EngineHealthView {
  code: EngineSummaryCode | "unknown";
  label: string;
  message: string;
  tone: Tone;
  /** Automated trading can actually run (supervisor active). */
  active: boolean;
  /** Worth a banner under the top bar (anything but a healthy, running engine). */
  banner: boolean;
}

const SUMMARY_TONE: Record<EngineSummary["tone"], Tone> = { ok: "positive", info: "info", warning: "warning", error: "negative" };

/**
 * What to say about the trading engine. The server keeps three things apart
 * (API service health, the trading supervisor, and permission to trade); this
 * only describes them. "Engine offline" is said only when the engine's API
 * cannot be reached. Older servers without `engine_summary` fall back to the
 * heartbeat state, which proves the supervisor is beating, not that the API is down.
 */
export function engineHealthView(status: TradingStatus): EngineHealthView {
  const s = status.engine_summary;
  if (s) {
    return { code: s.code, label: s.label, message: s.message, tone: SUMMARY_TONE[s.tone], active: s.trading_active, banner: !s.trading_active || s.code !== "running" };
  }
  if (status.engine_state === "offline") {
    return { code: "unknown", label: "Supervisor not running", message: status.engine_detail || "The trading supervisor is not reporting, so nothing will trade.", tone: "warning", active: false, banner: true };
  }
  if (status.engine_state === "degraded") {
    return { code: "running_degraded", label: "Running · attention", message: status.engine_detail, tone: "warning", active: true, banner: true };
  }
  return { code: "running", label: "Engine running", message: status.engine_detail, tone: "positive", active: true, banner: false };
}

/**
 * The single answer to "Is the robot running?". Order matters: a platform
 * halt overrides everything; then the user's own kill switch, because it is
 * the control the user acts on.
 */
export function deriveRobotStatus(status: TradingStatus): RobotStatus {
  if (status.platform_halted) {
    return {
      label: "Halted by admin",
      tone: "negative",
      detail: status.platform_halt_reason ?? "Trading is halted platform-wide by an administrator.",
      running: false,
    };
  }
  if (status.kill_switch_engaged) {
    return {
      label: "Trading stopped",
      tone: "warning",
      detail: status.kill_switch_reason ?? "Your trading is stopped. No new orders can be placed on your accounts.",
      running: false,
    };
  }
  if (status.trading_mode === "LIVE" && status.live_trading_locked) {
    return {
      label: "Blocked",
      tone: "negative",
      detail: "LIVE mode is selected but the server hard lock is on. Nothing can trade.",
      running: false,
    };
  }
  const engine = engineHealthView(status);
  if (!engine.active) {
    return { label: engine.label, tone: engine.tone, detail: engine.message, running: false };
  }
  if (engine.tone === "warning") {
    return { label: engine.label, tone: "warning", detail: engine.message, running: true };
  }
  return { label: "Running", tone: "positive", detail: "Strategies may open trades. Every order passes the risk engine.", running: true };
}

export const MODE_INFO: Record<TradingMode, { label: string; tone: Tone; explanation: string }> = {
  DEMO: {
    label: "Demo",
    tone: "info",
    explanation: "Orders may only go to demo accounts funded with virtual money.",
  },
  LIVE: {
    label: "LIVE",
    tone: "live",
    explanation: "Orders use REAL MONEY on live accounts.",
  },
};
