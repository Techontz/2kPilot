import type { TradingStatus } from "@/lib/types";

/** Test fixture only — never used by the application. */
export function tradingStatus(overrides: Partial<TradingStatus> = {}): TradingStatus {
  return {
    trading_mode: "DEMO",
    kill_switch_engaged: true,
    kill_switch_reason: "Initial state",
    kill_switch_changed_at: null,
    mode_changed_at: null,
    live_trading_locked: true,
    new_orders_permitted: false,
    engine_state: "offline",
    engine_detail: "Engine not built yet.",
    ...overrides,
  };
}
