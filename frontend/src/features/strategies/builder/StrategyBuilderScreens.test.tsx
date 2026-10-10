import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import catalogJson from "./__fixtures__/catalog.json";
import templates from "./__fixtures__/templates.json";
import { DRAFT_STORAGE_KEY } from "./draft";
import { EditStrategyScreen, NewStrategyScreen } from "./StrategyBuilderScreens";

const push = vi.fn();
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh: vi.fn(), replace: vi.fn() }), useSearchParams: () => search }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));
let isAdmin = false;
vi.mock("@/components/providers/SessionProvider", () => ({ useSession: () => ({ isAdmin }) }));

const ema = templates.find((t) => t.slug === "ema-crossover")!;
const version = { id: "v1", version: 3, code_version: "1", parameters: ema.parameters, rules_text: ema.rules_text, notes: "", created_at: "" };
const template = { id: "t-1", key: "rules", name: "EMA crossover", description: "", built_in: true, editable: true, copied_from_id: null, latest_version: version, versions: [version] };
const copy = { ...template, id: "s-1", name: "My EMA", built_in: false, copied_from_id: "t-1" };
const code = { ...template, id: "c-1", key: "trend_pullback", name: "Trend Pullback V1", latest_version: null, versions: [] };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("builder screens", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("csrf-cookie")) return new Response(null, { status: 204 });
      if (url.startsWith("/api/strategies/catalog")) return json(200, catalogJson);
      if (url.includes("/copy")) return json(201, { id: "s-new", name: "My EMA crossover" });
      return json(200, [template, copy, code]);
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    push.mockReset();
    sessionStorage.clear();
    search = new URLSearchParams();
    isAdmin = false;
  });

  it("edits your copy of a template", async () => {
    render(<EditStrategyScreen id="s-1" />);
    expect(await screen.findByText(/Your copy of EMA crossover/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toHaveValue("My EMA");
    expect(screen.getByRole("button", { name: "Save as a new version" })).toBeInTheDocument();
  });

  it("asks to copy a template first, then edits the copy", async () => {
    render(<EditStrategyScreen id="t-1" />);
    expect(await screen.findByText(/Templates are read-only — copy it first/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Copy and edit/ }));
    const call = fetchMock.mock.calls.find(([u]) => String(u).includes("/copy"))!;
    expect(String(call[0])).toBe("/api/strategies/t-1/copy");
    expect(JSON.parse(String(call[1]?.body))).toEqual({ name: "My EMA crossover" });
    expect(push).toHaveBeenCalledWith("/strategies/s-new/edit");
  });

  it("lets admins edit a template with a warning", async () => {
    isAdmin = true;
    render(<EditStrategyScreen id="t-1" />);
    expect(await screen.findByText("You're editing a shared template")).toBeInTheDocument();
  });

  it("explains that code strategies aren't edited here", async () => {
    render(<EditStrategyScreen id="c-1" />);
    expect(await screen.findByText(/can't be edited in the builder/)).toBeInTheDocument();
  });

  it("says when the strategy isn't there", async () => {
    render(<EditStrategyScreen id="nope" />);
    expect(await screen.findByText("Strategy not found")).toBeInTheDocument();
  });

  it("opens an AI draft for review", async () => {
    search = new URLSearchParams("from=draft");
    sessionStorage.setItem(
      DRAFT_STORAGE_KEY,
      JSON.stringify({ rules: ema.parameters, explanation: "Crossing averages.", warnings: [], unsupported: ["Martingale"], source: "ai" }),
    );
    render(<NewStrategyScreen />);
    expect(await screen.findByText("Crossing averages.")).toBeInTheDocument();
    expect(screen.getByText("Martingale")).toBeInTheDocument();
    expect(screen.getByText("Sell when EMA 9 crosses below EMA 21.")).toBeInTheDocument();
  });

  it("says when the draft is gone", async () => {
    search = new URLSearchParams("from=draft");
    render(<NewStrategyScreen />);
    expect(await screen.findByText("The draft isn't here any more")).toBeInTheDocument();
  });
});
