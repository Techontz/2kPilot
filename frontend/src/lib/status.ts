import type { TradingMode, TradingStatus } from "./types";

export type Tone = "positive" | "negative" | "warning" | "neutral" | "live" | "info";

export interface RobotStatus {
  label: string;
  tone: Tone;
  detail: string;
  running: boolean;
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
  if (status.engine_state === "offline") {
    return { label: "Engine offline", tone: "negative", detail: status.engine_detail, running: false };
  }
  if (status.engine_state === "degraded") {
    return { label: "Running · attention", tone: "warning", detail: status.engine_detail, running: true };
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
