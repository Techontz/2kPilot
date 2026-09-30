import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { tradingStatus } from "@/test/fixtures";
import type { SystemStatus, TradingStatus } from "@/lib/types";

const stopAllTrading = vi.fn();
const resumeTrading = vi.fn();
const applyTradingStatus = vi.fn();
let current: SystemStatus;
let isOwner = true;

vi.mock("@/lib/trading", () => ({
  stopAllTrading: (...args: unknown[]) => stopAllTrading(...args),
  resumeTrading: () => resumeTrading(),
}));
vi.mock("@/components/providers/SessionProvider", () => ({ useSession: () => ({ isOwner }) }));
vi.mock("@/components/providers/SystemStatusProvider", () => ({
  useSystemStatus: () => ({ status: current, applyTradingStatus }),
}));

const { KillSwitchButton } = await import("./KillSwitchButton");

function withTrading(trading: TradingStatus): SystemStatus {
  return { app_name: "2kFX", version: "0", environment: "test", broker_accounts_connected: 0, trading };
}

beforeEach(() => {
  vi.clearAllMocks();
  isOwner = true;
});

describe("KillSwitchButton", () => {
  it("stops trading in one click", async () => {
    current = withTrading(tradingStatus({ kill_switch_engaged: false }));
    stopAllTrading.mockResolvedValue(tradingStatus());
    render(<KillSwitchButton reason="news" />);
    await userEvent.click(screen.getByRole("button", { name: /stop all trading/i }));
    expect(stopAllTrading).toHaveBeenCalledWith("news");
    expect(applyTradingStatus).toHaveBeenCalled();
  });

  it("requires confirmation before resuming", async () => {
    current = withTrading(tradingStatus({ kill_switch_engaged: true }));
    resumeTrading.mockResolvedValue(tradingStatus({ kill_switch_engaged: false }));
    render(<KillSwitchButton />);
    await userEvent.click(screen.getByRole("button", { name: /resume trading/i }));
    expect(resumeTrading).not.toHaveBeenCalled();
    const confirmButtons = screen.getAllByRole("button", { name: /resume trading/i, hidden: true });
    await userEvent.click(confirmButtons.at(-1)!);
    expect(resumeTrading).toHaveBeenCalledTimes(1);
  });

  it("is hidden from read-only viewers", () => {
    isOwner = false;
    current = withTrading(tradingStatus({ kill_switch_engaged: false }));
    const { container } = render(<KillSwitchButton />);
    expect(container).toBeEmptyDOMElement();
  });
});
