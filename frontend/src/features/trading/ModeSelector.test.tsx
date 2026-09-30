import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { tradingStatus } from "@/test/fixtures";

vi.mock("@/components/providers/SessionProvider", () => ({ useSession: () => ({ isOwner: true }) }));
vi.mock("@/components/providers/SystemStatusProvider", () => ({
  useSystemStatus: () => ({ applyTradingStatus: vi.fn() }),
}));

const { ModeSelector } = await import("./ModeSelector");

describe("ModeSelector", () => {
  it("never offers LIVE while the server hard lock is on", () => {
    render(<ModeSelector trading={tradingStatus({ live_trading_locked: true })} />);
    expect(screen.getByRole("radio", { name: /live/i })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /backtest/i })).toBeEnabled();
  });

  it("blocks all mode changes while trading is running", () => {
    render(<ModeSelector trading={tradingStatus({ kill_switch_engaged: false })} />);
    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
  });
});
