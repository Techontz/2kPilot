import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Scorecard } from "./Scorecard";

vi.mock("@/components/providers/AppDataProvider", () => ({
  useAppData: () => ({ account: { id: "acc-1", label: "Deriv demo", environment: "DEMO", currency: "USD" } }),
}));

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const row = {
  strategy_id: "s-1", strategy: "EMA crossover", symbol: "frxUSDJPY", contract_family: "RISE_FALL",
  trades: 40, wins: 19, losses: 21, win_rate: 47.5, break_even_win_rate: 55.9, avg_win: 0.79, avg_loss: -1,
  expectancy: -0.15, net_pnl: -5.99, first_trade_at: null, last_trade_at: null,
  verdict: "NO_EDGE", verdict_text: "No proven edge: these results are what luck alone would give.", confidence_z: -1.1,
};

describe("Scorecard", () => {
  const fetchMock = vi.fn<typeof fetch>();
  let rows: unknown[] = [row];
  beforeEach(() => {
    rows = [row];
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("csrf-cookie")) return new Response(null, { status: 204 });
      if (url.includes("/analytics/scorecard") && url.includes("account_id=acc-1")) {
        return json(200, { account_id: "acc-1", simulated: false, min_trades: 30, rows });
      }
      return json(404, {});
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows the win rate against the break-even rate and the verdict", async () => {
    render(<Scorecard />);
    expect(await screen.findByText("EMA crossover")).toBeInTheDocument();
    expect(screen.getByText("No edge yet")).toBeInTheDocument();
    expect(screen.getByText("47.5%")).toHaveClass("text-negative"); // below the 55.9% needed
    expect(screen.getByText("55.9%")).toBeInTheDocument();
    expect(screen.getByText(/luck alone/)).toBeInTheDocument();
  });

  it("stays hidden until a strategy has traded", async () => {
    rows = [];
    const { container } = render(<Scorecard />);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
