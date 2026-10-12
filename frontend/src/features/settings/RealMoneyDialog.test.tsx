import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import type { Account, RiskProfile, TradingStatus, User } from "@/lib/types";
import { account, tradingStatus } from "@/test/fixtures";

const state: { status: TradingStatus; accounts: Account[]; user: User } = {
  status: tradingStatus(),
  accounts: [],
  user: { id: "u1", name: "Ada", email: "ada@example.com", role: "user", approved: true, mfa_enabled: true, mfa_required: false, last_login_at: null },
};
const reloadStatus = vi.fn(async () => state.status);
const setStatus = vi.fn();

vi.mock("@/components/providers/AppDataProvider", () => ({
  useAppData: () => ({
    status: state.status,
    statusUnknown: false,
    reloadStatus,
    setStatus,
    accounts: state.accounts,
    reloadAccounts: vi.fn(),
    account: state.accounts[0] ?? null,
    selectAccount: vi.fn(),
    unread: 0,
    reloadUnread: vi.fn(),
    live: false,
  }),
}));
vi.mock("@/components/providers/SessionProvider", () => ({
  useSession: () => ({ user: state.user, isAdmin: false, refresh: vi.fn(), logout: vi.fn() }),
}));

const PROFILE = {
  id: "rp-1", name: "Beginner", stake_amount: "1.00", max_stake_amount: "5.00", max_consecutive_losses: 3, max_daily_loss_amount: null,
  max_daily_loss_pct: "2.000", daily_profit_target_amount: null, max_trades_per_day: 20, max_open_positions: 3,
} as unknown as RiskProfile;

const apiMock = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api")>();
  return { ...real, api: (...args: unknown[]) => apiMock(...args) };
});

const { RealMoneyDialog } = await import("./RealMoneyDialog");
const { RealMoneyCard } = await import("./AccountsPanel");

const LIVE_ACCOUNT = account({ id: "live-1", label: "Deriv real", environment: "LIVE", broker: "Deriv", broker_account_id: "CR123", risk_profile: { id: "rp-1", name: "Beginner" } });

function renderDialog() {
  return render(<TooltipProvider><RealMoneyDialog open onOpenChange={() => {}} /></TooltipProvider>);
}

beforeEach(() => {
  apiMock.mockReset();
  reloadStatus.mockClear();
  setStatus.mockClear();
  apiMock.mockImplementation(async (path: string) => (path === "/risk/profiles" ? [PROFILE] : {}));
  state.status = tradingStatus({ live_trading_locked: false, live_confirmation_phrase: "ENABLE LIVE TRADING" });
  state.accounts = [account(), LIVE_ACCOUNT];
  state.user = { ...state.user, mfa_enabled: true };
});

describe("RealMoneyDialog", () => {
  it("explains the server lock and offers no way forward", () => {
    state.status = tradingStatus({ live_trading_locked: true });
    renderDialog();
    expect(screen.getByText(/The server administrator must enable it \(LIVE_TRADING_ENABLED\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
  });

  it("asks to stop trading first and stops it in one click", async () => {
    state.status = tradingStatus({ live_trading_locked: false, kill_switch_engaged: false });
    const user = userEvent.setup();
    renderDialog();
    expect(screen.getByText("Stop trading first")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stop trading" }));
    expect(apiMock).toHaveBeenCalledWith("/trading/stop", expect.objectContaining({ method: "POST" }));
    expect(await screen.findByText("Choose the real-money account")).toBeInTheDocument();
  });

  it("explains how to add a LIVE account when there is none", () => {
    state.accounts = [account()];
    renderDialog();
    expect(screen.getByText(/Add your Deriv real account in Settings → Brokers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("walks through limits, warning and credentials, and maps a wrong password to the password field", async () => {
    const user = userEvent.setup();
    apiMock.mockImplementation(async (path: string) => {
      if (path === "/risk/profiles") return [PROFILE];
      if (path === "/trading/mode") throw new ApiError(403, "password_incorrect", "Password confirmation failed.");
      return {};
    });
    renderDialog();
    // The only LIVE account is preselected.
    expect(screen.getByRole("radio", { name: /Deriv real/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Each trade risks $1.00 (stake per trade)")).toBeInTheDocument();
    expect(screen.getByText("Daily profit target: No limit set")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText(/You can lose your entire trading balance\. Automated strategies can and do lose money/)).toBeInTheDocument();
    const next = screen.getByRole("button", { name: "Continue" });
    expect(next).toBeDisabled();
    await user.click(screen.getByLabelText("I understand I can lose my entire trading balance."));
    await user.click(next);

    const submit = screen.getByRole("button", { name: "Turn on LIVE mode" });
    await user.type(screen.getByLabelText("Code from your authenticator app"), "123456");
    await user.type(screen.getByLabelText("Your password"), "wrong");
    await user.type(screen.getByLabelText(/to confirm/), "enable live trading");
    expect(submit).toBeDisabled(); // phrase must match exactly
    await user.clear(screen.getByLabelText(/to confirm/));
    await user.type(screen.getByLabelText(/to confirm/), "ENABLE LIVE TRADING");
    await user.click(submit);

    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/trading/mode", {
      method: "PUT",
      body: { mode: "LIVE", account_id: "live-1", password: "wrong", confirmation_phrase: "ENABLE LIVE TRADING", mfa_code: "123456" },
    }));
    expect(await screen.findByText("That password is not correct.")).toBeInTheDocument();
    expect(screen.getByLabelText("Your password")).toHaveAttribute("aria-invalid", "true");
  });

  it("blocks the last step without two-factor authentication", async () => {
    state.user = { ...state.user, mfa_enabled: false };
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Each trade risks $1.00 (stake per trade)");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByLabelText("I understand I can lose my entire trading balance."));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("link", { name: "Set up two-factor authentication first" })).toHaveAttribute("href", "/settings?tab=security");
    expect(screen.getByRole("button", { name: "Turn on LIVE mode" })).toBeDisabled();
  });

  it("blocks an account without a risk profile with a link to Accounts", async () => {
    state.accounts = [{ ...LIVE_ACCOUNT, risk_profile: null }];
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("link", { name: /Go to Settings → Accounts/ })).toHaveAttribute("href", "/settings?tab=accounts");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });
});

describe("RealMoneyCard", () => {
  it("shows the server lock and keeps authorising disabled", () => {
    state.status = tradingStatus({ live_trading_locked: true });
    render(<TooltipProvider><RealMoneyCard /></TooltipProvider>);
    expect(screen.getByText(/Real-money trading is locked on this server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Authorize real-money trading/ })).toBeDisabled();
  });

  it("returns to Demo, offering to stop trading first when the server says so", async () => {
    state.status = tradingStatus({ trading_mode: "LIVE", kill_switch_engaged: false, live_trading_locked: false });
    let first = true;
    apiMock.mockImplementation(async (path: string) => {
      if (path === "/trading/mode" && first) {
        first = false;
        throw new ApiError(409, "stop_first", "Stop your trading before changing the operating mode.");
      }
      return {};
    });
    const user = userEvent.setup();
    render(<TooltipProvider><RealMoneyCard /></TooltipProvider>);
    await user.click(screen.getByRole("button", { name: /Return to Demo/ }));
    await user.click(await screen.findByRole("button", { name: "Stop trading and return to Demo" }));
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/trading/stop", expect.anything()));
    expect(apiMock).toHaveBeenLastCalledWith("/trading/mode", { method: "PUT", body: { mode: "DEMO" } });
  });
});
