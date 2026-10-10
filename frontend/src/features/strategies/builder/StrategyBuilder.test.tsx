import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuleSet, RulesCatalog } from "@/lib/types";
import catalogJson from "./__fixtures__/catalog.json";
import templates from "./__fixtures__/templates.json";
import { shortProblem } from "./ConditionRow";
import { defaultState, rulesToState } from "./model";
import { StrategyBuilder, timeframeText } from "./StrategyBuilder";

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh, replace: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));

const catalog = catalogJson as unknown as RulesCatalog;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("StrategyBuilder", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    push.mockReset();
  });

  const calls = () => fetchMock.mock.calls.filter(([url]) => !String(url).includes("csrf-cookie"));

  it("shows the live plain-English preview and updates it", async () => {
    render(<StrategyBuilder catalog={catalog} initial={defaultState(catalog)} />);
    const preview = screen.getByRole("complementary", { name: "Preview and save" });
    expect(within(preview).getByText("Buy when EMA 9 crosses above EMA 21.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: "Use a sell rule" }));
    expect(within(preview).getByText("Sell when EMA 9 crosses below EMA 21.")).toBeInTheDocument();
    const period = screen.getAllByRole("spinbutton", { name: "Left side: EMA period" })[0]!;
    await userEvent.clear(period);
    await userEvent.type(period, "12");
    expect(within(preview).getByText("Buy when EMA 12 crosses above EMA 21.")).toBeInTheDocument();
  });

  it("does not save with local problems and says why", async () => {
    render(<StrategyBuilder catalog={catalog} initial={defaultState(catalog)} />);
    await userEvent.click(screen.getByRole("button", { name: "Save strategy" }));
    expect(calls()).toHaveLength(0);
    expect(screen.getByRole("alert")).toHaveTextContent("Give the strategy a name");
    expect(screen.getByLabelText(/^Name/)).toHaveAttribute("aria-invalid", "true");
  });

  it("shows a problem next to the condition that causes it", async () => {
    render(<StrategyBuilder catalog={catalog} initial={{ ...defaultState(catalog), name: "X" }} />);
    const period = screen.getAllByRole("spinbutton", { name: "Right side: EMA period" })[0]!;
    await userEvent.clear(period);
    await userEvent.type(period, "9");
    const group = screen.getByRole("group", { name: "Condition 1" });
    expect(within(group).getByText("EMA 9 is compared with itself")).toBeInTheDocument();
    expect(group).toHaveAttribute("aria-invalid", "true");
  });

  it("creates a new strategy and offers next steps", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie") ? new Response(null, { status: 204 }) : json(201, { id: "s-1", name: "Mine", latest_version: { version: 1 } }),
    );
    render(<StrategyBuilder catalog={catalog} initial={{ ...defaultState(catalog), name: "Mine" }} source="ai" />);
    await userEvent.click(screen.getByRole("button", { name: "Save strategy" }));
    const [url, init] = calls()[0]!;
    expect(String(url)).toBe("/api/strategies");
    const body = JSON.parse(String(init?.body));
    expect(body).toMatchObject({ name: "Mine", description: "", source: "ai" });
    expect(body.rules.entry.buy.all).toHaveLength(1);
    expect(JSON.stringify(body.rules)).not.toContain("null,");
    expect(await screen.findByRole("link", { name: /Test it on history/ })).toHaveAttribute("href", "/strategies?test=s-1");
    expect(screen.getByRole("link", { name: /Activate it/ })).toHaveAttribute("href", "/strategies?activate=s-1");
    expect(screen.getByRole("link", { name: "Back to my strategies" })).toHaveAttribute("href", "/strategies");
  });

  it("lists the engine's problems and field errors from a 422", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie")
        ? new Response(null, { status: 204 })
        : json(422, { message: "This strategy has problems", code: "invalid_strategy_config", problems: ["Buy rule, condition 1: something is off"] }),
    );
    render(<StrategyBuilder catalog={catalog} initial={{ ...defaultState(catalog), name: "Mine" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Save strategy" }));
    expect(await screen.findByText("The rules need a fix:")).toBeInTheDocument();
    expect(screen.getByText("Buy rule, condition 1: something is off")).toBeInTheDocument();
  });

  it("shows a taken name under the name field", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie") ? new Response(null, { status: 204 }) : json(422, { message: "taken", errors: { name: ["You already have a strategy with this name."] } }),
    );
    render(<StrategyBuilder catalog={catalog} initial={{ ...defaultState(catalog), name: "Mine" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Save strategy" }));
    expect(await screen.findByText("You already have a strategy with this name.")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toHaveAttribute("aria-invalid", "true");
  });

  it("saves an edit as a new version, renaming first when needed", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).includes("csrf-cookie")) return new Response(null, { status: 204 });
      return init?.method === "PATCH" ? json(200, { id: "s-9" }) : json(201, { id: "v-2", version: 2 });
    });
    const t = templates.find((x) => x.slug === "ema-crossover")!;
    const initial = rulesToState(t.parameters as unknown as RuleSet, catalog, { name: "Copy", description: "" });
    render(<StrategyBuilder catalog={catalog} initial={initial} strategy={{ id: "s-9", name: "Copy", description: "" }} />);
    await userEvent.type(screen.getByLabelText(/^Name/), " 2");
    await userEvent.click(screen.getByRole("switch", { name: "Use a sell rule" })); // sell off
    await userEvent.click(screen.getByRole("button", { name: "Save as a new version" }));
    const [first, second] = calls();
    expect(String(first![0])).toBe("/api/strategies/s-9");
    expect(JSON.parse(String(first![1]?.body))).toEqual({ name: "Copy 2", description: "" });
    expect(String(second![0])).toBe("/api/strategies/s-9/versions");
    const body = JSON.parse(String(second![1]?.body));
    expect(Object.keys(body.rules.entry)).toEqual(["buy"]);
    expect(await screen.findByText("Saved “Copy 2” as version 2")).toBeInTheDocument();
  });

  it("does nothing when an edit has no changes", async () => {
    const t = templates[0]!;
    const initial = rulesToState(t.parameters as unknown as RuleSet, catalog, { name: "Same", description: "" });
    render(<StrategyBuilder catalog={catalog} initial={initial} strategy={{ id: "s-1", name: "Same", description: "" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Save as a new version" }));
    expect(calls()).toHaveLength(0);
  });

  it("explains each contract family's exits", () => {
    render(<StrategyBuilder catalog={catalog} initial={defaultState(catalog)} />);
    expect(screen.getByText(catalog.contract_notes.RISE_FALL!)).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("shortens problems shown next to their row", () => {
    expect(shortProblem("Buy rule, condition 2 (left side): EMA period must be between 1 and 500")).toBe("Left side: EMA period must be between 1 and 500");
    expect(shortProblem("Filter 1: A condition must look at the market, not only at fixed numbers")).toBe("A condition must look at the market, not only at fixed numbers");
    expect(shortProblem("Something else")).toBe("Something else");
  });

  it("describes timeframes in plain words", () => {
    expect(timeframeText("M5")).toBe("Checked when each 5-minute candle closes");
    expect(timeframeText("D1")).toBe("Checked when each daily candle closes");
  });
});
