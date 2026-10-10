import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import type { TradingStatus } from "@/lib/types";
import { tradingStatus } from "@/test/fixtures";
import { ModePill } from "./ModePill";
import { BigTradingButton, BotStatus, TradingControlProvider, TradingToggle } from "./TradingControls";

const api = vi.fn();
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: (...args: unknown[]) => api(...args),
  ensureCsrf: vi.fn(async () => undefined),
}));
vi.mock("@/features/settings/RealMoneyDialog", () => ({ RealMoneyDialog: () => null }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let status: TradingStatus | null = tradingStatus();
let statusUnknown = false;
/** What GET /trading/status answers next (the dialog always asks for a fresh status). */
const reloadStatus = vi.fn(async (): Promise<TradingStatus | null> => status);
const setStatus = vi.fn();
vi.mock("../providers/AppDataProvider", () => ({ useAppData: () => ({ status, statusUnknown, reloadStatus, setStatus }) }));

const running = () => tradingStatus({ kill_switch_engaged: false, engine_state: "running" });

function renderControls() {
  return render(
    <TooltipProvider>
      <TradingControlProvider>
        <TradingToggle />
        <BotStatus />
        <BigTradingButton />
      </TradingControlProvider>
    </TooltipProvider>,
  );
}

beforeEach(() => {
  api.mockReset().mockResolvedValue({});
  reloadStatus.mockReset().mockImplementation(async () => status);
  setStatus.mockClear();
  vi.mocked(toast.error).mockClear();
  status = tradingStatus();
  statusUnknown = false;
});

describe("Stop", () => {
  it("stops with one click — no confirmation — and shows the returned status at once", async () => {
    status = running();
    const stopped = tradingStatus({ kill_switch_engaged: true, kill_switch_reason: "Stopped from the dashboard" });
    api.mockResolvedValue(stopped);
    render(<TradingControlProvider><TradingToggle /></TradingControlProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Stop trading" }));
    expect(api).toHaveBeenCalledWith("/trading/stop", expect.objectContaining({ method: "POST" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(setStatus).toHaveBeenCalledWith(stopped));
    expect(reloadStatus).not.toHaveBeenCalled(); // no refetch: the answer IS the status
  });

  it("is offered (enabled) while the status is still loading", () => {
    status = null;
    renderControls();
    const stops = screen.getAllByRole("button", { name: /Stop trading/ });
    expect(stops).toHaveLength(2);
    for (const button of stops) expect(button).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Start/ })).toBeNull();
  });

  it("is offered and the last-known state is hidden when the status cannot be loaded", () => {
    status = tradingStatus({ kill_switch_engaged: true, trading_mode: "DEMO" }); // last known: stopped
    statusUnknown = true;
    render(
      <TooltipProvider>
        <TradingControlProvider><TradingToggle /><BotStatus /></TradingControlProvider>
        <ModePill />
      </TooltipProvider>,
    );
    expect(screen.getByRole("button", { name: "Stop trading" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Start trading" })).toBeNull();
    expect(screen.getByLabelText("Bot: Status unknown — reconnecting")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Status unknown — reconnecting" })).toBeInTheDocument();
    expect(screen.queryByText("DEMO")).toBeNull();
  });

  it("retries after a 429, waiting for Retry-After", async () => {
    status = running();
    const stopped = tradingStatus({ kill_switch_engaged: true });
    api.mockRejectedValueOnce(new ApiError(429, "http_error", "Too Many Attempts.", {}, [], 0)).mockResolvedValueOnce(stopped);
    render(<TradingControlProvider><TradingToggle /></TradingControlProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Stop trading" }));
    await waitFor(() => expect(setStatus).toHaveBeenCalledWith(stopped));
    expect(api).toHaveBeenCalledTimes(2);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("says clearly when stopping failed", async () => {
    status = running();
    api.mockRejectedValue(new ApiError(500, "http_error", "Server error."));
    render(<TradingControlProvider><TradingToggle /></TradingControlProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Stop trading" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Could not stop trading", expect.objectContaining({ description: expect.stringMatching(/Server error\. Press Stop again/) })));
    expect(setStatus).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Stop trading" })).toBeEnabled();
  });
});

describe("Start", () => {
  it("asks before starting, with the wording of a freshly loaded status", async () => {
    status = tradingStatus({ kill_switch_engaged: true });
    render(<TradingControlProvider><TradingToggle /></TradingControlProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Start trading" }));
    expect(api).not.toHaveBeenCalled();
    expect(reloadStatus).toHaveBeenCalledTimes(1);
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() => expect(dialog).toHaveTextContent(/virtual money/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Start trading" }));
    expect(api).toHaveBeenCalledWith("/trading/resume", { method: "POST", body: { confirm: true, live: false } });
  });

  it("uses the LIVE wording and sends live: true when the fresh status says LIVE", async () => {
    status = tradingStatus({ kill_switch_engaged: true, trading_mode: "DEMO" }); // stale copy on screen
    const fresh = tradingStatus({ kill_switch_engaged: true, trading_mode: "LIVE", live_trading_locked: false });
    reloadStatus.mockResolvedValue(fresh);
    const started = { ...fresh, kill_switch_engaged: false };
    api.mockResolvedValue(started);
    render(<TradingControlProvider><TradingToggle /></TradingControlProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Start trading" }));
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() => expect(dialog).toHaveTextContent(/REAL money/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Start with real money" }));
    expect(api).toHaveBeenCalledWith("/trading/resume", { method: "POST", body: { confirm: true, live: true } });
    await waitFor(() => expect(setStatus).toHaveBeenCalledWith(started));
  });

  it("re-asks with the LIVE wording when the server says the mode is LIVE", async () => {
    status = tradingStatus({ kill_switch_engaged: true });
    const live = tradingStatus({ kill_switch_engaged: true, trading_mode: "LIVE", live_trading_locked: false });
    reloadStatus.mockResolvedValueOnce(status).mockResolvedValueOnce(live);
    api.mockRejectedValueOnce(new ApiError(409, "live_confirmation_required", "Confirm starting LIVE trading.")).mockResolvedValueOnce({ ...live, kill_switch_engaged: false });
    render(<TradingControlProvider><TradingToggle /></TradingControlProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Start trading" }));
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() => expect(dialog).toHaveTextContent(/virtual money/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Start trading" }));
    expect(api).toHaveBeenLastCalledWith("/trading/resume", { method: "POST", body: { confirm: true, live: false } });

    await waitFor(() => expect(dialog).toHaveTextContent(/REAL money/));
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/LIVE mode now/);
    await userEvent.click(within(dialog).getByRole("button", { name: "Start with real money" }));
    expect(api).toHaveBeenLastCalledWith("/trading/resume", { method: "POST", body: { confirm: true, live: true } });
  });

  it("cannot start while the status cannot be checked", async () => {
    status = tradingStatus({ kill_switch_engaged: true });
    reloadStatus.mockResolvedValue(null);
    render(<TradingControlProvider><TradingToggle /></TradingControlProvider>);
    await userEvent.click(screen.getByRole("button", { name: "Start trading" }));
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() => expect(within(dialog).getByRole("alert")).toHaveTextContent(/Can't check your trading status/));
    expect(within(dialog).getByRole("button", { name: "Start trading" })).toBeDisabled();
  });
});

describe("ModePill", () => {
  it("shows DEMO by default and a loud LIVE for real money", () => {
    status = tradingStatus({ trading_mode: "DEMO" });
    const { rerender } = render(<TooltipProvider><ModePill /></TooltipProvider>);
    expect(screen.getByText("DEMO")).toBeInTheDocument();
    expect(screen.getByLabelText(/Demo mode — virtual money/)).toBeInTheDocument();
    status = tradingStatus({ trading_mode: "LIVE" });
    rerender(<TooltipProvider><ModePill /></TooltipProvider>);
    expect(screen.getByLabelText(/LIVE mode — real money/)).toBeInTheDocument();
  });

  it("explains why real-money authorization was revoked", async () => {
    status = tradingStatus({ trading_mode: "DEMO", live_revoked_reason: "Real-money authorization was revoked because your password was changed." });
    render(<TooltipProvider><ModePill /></TooltipProvider>);
    await userEvent.click(screen.getByLabelText(/Demo mode — virtual money/));
    expect(await screen.findByText(/revoked because your password was changed/)).toBeInTheDocument();
  });
});
