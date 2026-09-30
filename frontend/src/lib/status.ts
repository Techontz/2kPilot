import type { TradingMode, TradingStatus } from "./types";

export type Tone = "positive" | "negative" | "warning" | "neutral" | "live" | "info";

export interface RobotStatus {
  label: string;
  tone: Tone;
  detail: string;
  running: boolean;
}

/**
 * The single answer to "Is the robot running?". Order matters: the kill
 * switch is reported first because it is the control the user acts on.
 */
export function deriveRobotStatus(status: TradingStatus): RobotStatus {
  if (status.kill_switch_engaged) {
    return {
      label: "Trading stopped",
      tone: "warning",
      detail: status.kill_switch_reason ?? "The kill switch is engaged. No new orders can be placed.",
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
    return { label: "Robot offline", tone: "neutral", detail: status.engine_detail, running: false };
  }
  return { label: "Running", tone: "positive", detail: "Strategies may place orders.", running: true };
}

export const MODE_INFO: Record<TradingMode, { label: string; tone: Tone; explanation: string }> = {
  BACKTEST: {
    label: "Backtest",
    tone: "neutral",
    explanation: "Simulation on historical data only. No orders are ever sent to a broker.",
  },
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
