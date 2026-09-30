import { apiRequest } from "./api";
import type { TradingMode, TradingStatus } from "./types";

export const LIVE_CONFIRMATION_PHRASE = "ENABLE LIVE TRADING";

export function stopAllTrading(reason?: string): Promise<TradingStatus> {
  return apiRequest<TradingStatus>("/trading/stop", {
    method: "POST",
    body: reason ? { reason } : {},
  });
}

export function resumeTrading(): Promise<TradingStatus> {
  return apiRequest<TradingStatus>("/trading/resume", { method: "POST", body: { confirm: true } });
}

export function setTradingMode(
  mode: TradingMode,
  confirmation?: { password: string; phrase: string },
): Promise<TradingStatus> {
  return apiRequest<TradingStatus>("/trading/mode", {
    method: "PUT",
    body: {
      mode,
      password: confirmation?.password,
      confirmation_phrase: confirmation?.phrase,
    },
  });
}
