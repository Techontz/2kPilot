import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Strategy } from "@/lib/types";
import { account } from "@/test/fixtures";
import { BacktestDialog } from "./BacktestDialog";
import templates from "./builder/__fixtures__/templates.json";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh: vi.fn(), replace: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));
// A Paper account only: it keeps no past prices, so practice data is the default source.
vi.mock("@/components/providers/AppDataProvider", () => ({ useAppData: () => ({ accounts: [account()], account: account() }) }));

const ema = templates.find((t) => t.slug === "ema-crossover")!;
const strategy = {
  id: "s-1",
  key: "rules",
  name: ema.name,
  details: { suggested_symbols: ["R_75"], suggested_timeframe: "M5" },
  versions: [{ id: "v-1", version: 1, parameters: ema.parameters }],
  latest_version: { id: "v-1", version: 1, parameters: ema.parameters },
} as unknown as Strategy;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("BacktestDialog practice data", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("csrf-cookie")) return new Response(null, { status: 204 });
      if (url.includes("/datasets/synthetic")) {
        return json(201, { id: "d-1", symbol: "R_75", timeframe: "M5", source: "synthetic", first_bar: "2026-09-01T00:00:00Z", last_bar: "2026-10-01T00:00:00Z" });
      }
      if (url.includes("/backtests") && init?.method === "POST") return json(201, { id: "b-1" });
      return json(200, []);
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    push.mockReset();
  });

  it("defaults to practice data on the strategy's own 5-minute candles", async () => {
    render(<TooltipProvider><BacktestDialog strategy={strategy} open onOpenChange={vi.fn()} /></TooltipProvider>);
    expect(screen.getByRole("combobox", { name: "Candles" })).toHaveTextContent("5-minute candles (strategy)");
    expect(screen.getByRole("combobox", { name: "Use prices from" })).toHaveTextContent("Practice data");
    expect(screen.getByText(/2kPilot generates M5 candles/)).toBeInTheDocument();
    expect(screen.queryByText(/15-minute candles or longer/)).not.toBeInTheDocument();

    const run = screen.getByRole("button", { name: /Run the test/ });
    await waitFor(() => expect(run).toBeEnabled());
    await userEvent.click(run);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/strategies/backtests/b-1"));
    const synthetic = fetchMock.mock.calls.find(([url]) => String(url).includes("/datasets/synthetic"));
    expect(JSON.parse(String(synthetic?.[1]?.body))).toEqual({ symbol: "R_75", timeframe: "M5", days: 30 });
  });
});
