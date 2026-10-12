import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Strategy } from "@/lib/types";
import { StrategyInsights } from "./StrategyInsights";

let admin = false;
vi.mock("@/components/providers/SessionProvider", () => ({ useSession: () => ({ isAdmin: admin }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));

const strategy = {
  id: "s-1",
  key: "adaptive_trend_momentum",
  name: "Adaptive Trend & Momentum",
  description: "Uses trend, momentum, and volatility filters to identify potential trading opportunities while controlling risk.",
  built_in: true,
  code_version: "1.0.0",
  parameter_schema: { properties: {} },
  contract_families: ["SPOT", "MULTIPLIER"],
  symbols: ["R_10", "R_25"],
  entries_disabled: null,
  versions: [{ id: "v-1", version: 1, code_version: "1.0.0", parameters: { min_adx: 25, risk_per_trade_pct: 0.5, max_daily_loss_pct: 2, max_open_positions: 1 }, notes: "", created_at: "" }],
  assignments: [{ id: "a-1", strategy_id: "s-1", strategy_version_id: "v-1", version: 1, account: null, symbol: "R_10", status: "ENABLED", status_reason: null, last_bar_evaluated: null, last_signal_at: "2026-10-11T08:00:00Z" }],
  backtests_by_symbol: [{
    id: "b-1", name: "R_10 walk-forward", symbol: "R_10", timeframe: "M5", net_pnl: -5.8, return_pct: -0.58, win_rate: 33, trades: 609, max_drawdown: 10.77, max_drawdown_pct: 1.07,
    contract_family: "MULTIPLIER", run_at: null, data_source: "broker", profit_factor: 0.95, expectancy: -0.01,
    validation: { qualifies_for_demo_forward_testing: false, checks: [{ name: "Positive expectancy after costs", passed: false, detail: "-0.01 per trade out of sample" }], reasons: ["-0.01 per trade out of sample"], note: "Informational only" },
  }],
  live_trades: 0,
  live_net_pnl: 0,
  last_backtest: null,
} as unknown as Strategy;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("StrategyInsights", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    admin = false;
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("csrf-cookie")) return new Response(null, { status: 204 });
      if (url.includes("/admin/strategies/s-1/disable") && init?.method === "POST") return json(200, { id: "s-1", entries_disabled: true });
      if (url.includes("/assignments/a-1/evaluations")) {
        return json(200, {
          signals: [],
          evaluations: { data: [{ id: 9, bar_time: "2026-10-11T08:00:00Z", outcome: "NO_SETUP", summary: "No trade: regime SIDEWAYS — ADX 14.2 below 20: no trend",
            checks: [{ name: "Market regime", passed: false, detail: "SIDEWAYS — ADX 14.2 below 20: no trend" }] }], current_page: 1, last_page: 1, total: 1, per_page: 1 },
        });
      }
      return json(404, {});
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows markets, contracts, risk caps, the latest decision and the honest backtest verdict", async () => {
    render(<StrategyInsights strategy={strategy} />);
    expect(screen.getByText("R_10, R_25")).toBeInTheDocument();
    expect(screen.getByText("Multiplier (Deriv) · Spot (Paper) · not Rise/Fall")).toBeInTheDocument();
    const cap = screen.getByText("Risk per trade (max, % of balance)").closest("li");
    expect(cap).toHaveTextContent("Risk per trade (max, % of balance)0.5%");
    expect(await screen.findByText("Sideways")).toBeInTheDocument();
    expect(screen.getByText("No trade")).toBeInTheDocument();
    expect(screen.getByText("Not validated for demo forward testing")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Stop new entries/ })).not.toBeInTheDocument();
  });

  it("lets an admin stop new entries with a reason", async () => {
    admin = true;
    const onChanged = vi.fn();
    render(<StrategyInsights strategy={strategy} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: /Stop new entries/ }));
    await userEvent.type(screen.getByLabelText(/Reason/), "Feed under review");
    await userEvent.click(screen.getByRole("button", { name: "Stop new entries" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/disable"));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ reason: "Feed under review" });
  });

  it("warns when an administrator stopped the strategy", () => {
    render(<StrategyInsights strategy={{ ...strategy, assignments: [], entries_disabled: { at: null, reason: "Feed under review", inherited: false } }} />);
    expect(screen.getByText("New trades are stopped by an administrator")).toBeInTheDocument();
    expect(screen.getByText("Entries stopped")).toBeInTheDocument();
  });
});
