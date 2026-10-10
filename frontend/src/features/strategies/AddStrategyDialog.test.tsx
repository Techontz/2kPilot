import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import type { RulesCatalog } from "@/lib/types";
import { AddStrategyDialog, AI_NOT_CONFIGURED, draftErrorMessage, parseStrategyFile } from "./AddStrategyDialog";
import catalogJson from "./builder/__fixtures__/catalog.json";
import templates from "./builder/__fixtures__/templates.json";
import { DRAFT_STORAGE_KEY } from "./builder/draft";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh: vi.fn(), replace: vi.fn() }) }));
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({ toast: { success: (m: string) => toastSuccess(m), info: vi.fn(), error: vi.fn() } }));

const catalog = catalogJson as unknown as RulesCatalog;
const aiOn: RulesCatalog = { ...catalog, ai_drafting_available: true };
const aiOff: RulesCatalog = { ...catalog, ai_drafting_available: false };
const ema = templates.find((t) => t.slug === "ema-crossover")!;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("AddStrategyDialog", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const onOpenChange = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    push.mockReset();
    onOpenChange.mockReset();
    toastSuccess.mockReset();
    sessionStorage.clear();
  });
  const calls = () => fetchMock.mock.calls.filter(([url]) => !String(url).includes("csrf-cookie"));

  it("routes to templates and the builder", async () => {
    render(<AddStrategyDialog open onOpenChange={onOpenChange} catalog={aiOn} />);
    await userEvent.click(screen.getByRole("button", { name: /Start from a template/ }));
    expect(push).toHaveBeenCalledWith("/strategies?tab=templates");
    expect(onOpenChange).toHaveBeenCalledWith(false);
    await userEvent.click(screen.getByRole("button", { name: /Build it step by step/ }));
    expect(push).toHaveBeenLastCalledWith("/strategies/new");
  });

  it("disables plain-English drafting when it isn't configured", () => {
    render(<AddStrategyDialog open onOpenChange={onOpenChange} catalog={aiOff} />);
    const c = screen.getByRole("button", { name: /Describe it in your words/ });
    expect(c).toBeDisabled();
    expect(c).toHaveTextContent(AI_NOT_CONFIGURED);
  });

  it("drafts from a description and hands the draft to the builder", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie")
        ? new Response(null, { status: 204 })
        : json(200, { rules: ema.parameters, rules_text: ema.rules_text, explanation: "An EMA cross.", warnings: ["Late signals"], unsupported: ["News trading"], notes: [], model: "m" }),
    );
    render(<AddStrategyDialog open onOpenChange={onOpenChange} catalog={aiOn} />);
    await userEvent.click(screen.getByRole("button", { name: /Describe it in your words/ }));
    expect(screen.getByText(/sent to Anthropic/)).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: /Draft the rules/ });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Your strategy idea"), "Buy when EMA 9 crosses above EMA 21");
    await userEvent.click(submit);
    expect(JSON.parse(String(calls()[0]![1]?.body))).toEqual({ description: "Buy when EMA 9 crosses above EMA 21" });
    expect(await screen.findByText("An EMA cross.")).toBeInTheDocument();
    expect(screen.getByText("Buy when EMA 9 crosses above EMA 21.")).toBeInTheDocument();
    expect(screen.getByText("Not possible here:")).toBeInTheDocument();
    expect(screen.getByText("News trading")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review and edit in the builder" }));
    expect(push).toHaveBeenCalledWith("/strategies/new?from=draft");
    const stored = JSON.parse(sessionStorage.getItem(DRAFT_STORAGE_KEY) ?? "{}");
    expect(stored).toMatchObject({ source: "ai", explanation: "An EMA cross.", warnings: ["Late signals"], unsupported: ["News trading"] });
    expect(stored.rules.timeframe).toBe("M5");
  });

  it("explains when no rules could be drafted", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie")
        ? new Response(null, { status: 204 })
        : json(200, { rules: null, rules_text: null, explanation: "That needs news data.", warnings: [], unsupported: ["News"], notes: [], model: "m" }),
    );
    render(<AddStrategyDialog open onOpenChange={onOpenChange} catalog={aiOn} />);
    await userEvent.click(screen.getByRole("button", { name: /Describe it in your words/ }));
    await userEvent.type(screen.getByLabelText("Your strategy idea"), "Trade the news headlines");
    await userEvent.click(screen.getByRole("button", { name: /Draft the rules/ }));
    expect(await screen.findByText("No rules could be drafted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review and edit in the builder" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Change the description/ }));
    expect(screen.getByLabelText("Your strategy idea")).toHaveValue("Trade the news headlines");
  });

  it("shows drafting errors in plain English", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("csrf-cookie") ? new Response(null, { status: 204 }) : json(503, { message: "x", code: "ai_not_configured" }),
    );
    render(<AddStrategyDialog open onOpenChange={onOpenChange} catalog={aiOn} />);
    await userEvent.click(screen.getByRole("button", { name: /Describe it in your words/ }));
    await userEvent.type(screen.getByLabelText("Your strategy idea"), "Buy on a breakout please");
    await userEvent.click(screen.getByRole("button", { name: /Draft the rules/ }));
    expect(await screen.findByText(AI_NOT_CONFIGURED)).toBeInTheDocument();
  });

  it("imports a file, retrying with a new name after a conflict", async () => {
    let attempt = 0;
    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes("csrf-cookie")) return new Response(null, { status: 204 });
      attempt += 1;
      return attempt === 1
        ? json(422, { message: "taken", errors: { name: ["You already have a strategy with this name — rename it before importing."] } })
        : json(201, { id: "s-2", name: "Renamed" });
    });
    const onImported = vi.fn();
    render(<AddStrategyDialog open onOpenChange={onOpenChange} catalog={aiOn} onImported={onImported} />);
    await userEvent.click(screen.getByRole("button", { name: /Import a strategy file/ }));
    const content = JSON.stringify({ format: "tradepilot.strategy", schema_version: 1, name: "EMA", description: "d", rules: ema.parameters });
    await userEvent.upload(screen.getByLabelText("Strategy file"), new File([content], "ema.tradepilot.json", { type: "application/json" }));
    const name = await screen.findByLabelText("Name");
    expect(name).toHaveValue("EMA");
    await userEvent.click(screen.getByRole("button", { name: /Import/ }));
    expect(await screen.findByText(/rename it before importing/)).toBeInTheDocument();
    await userEvent.clear(name);
    await userEvent.type(name, "Renamed");
    await userEvent.click(screen.getByRole("button", { name: /Import/ }));
    const body = JSON.parse(String(calls()[1]![1]?.body));
    expect(body).toMatchObject({ format: "tradepilot.strategy", schema_version: 1, name: "Renamed" });
    expect(toastSuccess).toHaveBeenCalledWith("Imported “Renamed”");
    expect(onImported).toHaveBeenCalledWith({ id: "s-2", name: "Renamed" });
    expect(push).toHaveBeenCalledWith("/strategies");
  });

  it("refuses files that aren't JSON", async () => {
    render(<AddStrategyDialog open onOpenChange={onOpenChange} catalog={aiOn} />);
    await userEvent.click(screen.getByRole("button", { name: /Import a strategy file/ }));
    await userEvent.upload(screen.getByLabelText("Strategy file"), new File(["nope"], "x.json", { type: "application/json" }));
    expect(await screen.findByText(/isn't valid JSON/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Import/ })).toBeDisabled();
  });
});

describe("helpers", () => {
  it("parses strategy files", () => {
    expect(parseStrategyFile("[]")).toEqual({ ok: false, error: "This file doesn't contain a strategy." });
    expect(parseStrategyFile('{"format":"other"}')).toEqual({ ok: false, error: "This is not a 2kPilot strategy file." });
    expect(parseStrategyFile('{"format":"tradepilot.strategy"}')).toEqual({ ok: false, error: "This strategy file has no rules." });
    expect(parseStrategyFile('{"format":"tradepilot.strategy","rules":{}}').ok).toBe(true);
  });

  it("maps draft error codes", () => {
    expect(draftErrorMessage(new ApiError(503, "ai_not_configured", "x"))).toBe(AI_NOT_CONFIGURED);
    expect(draftErrorMessage(new ApiError(422, "ai_refused", "x"))).toMatch(/declined/);
    expect(draftErrorMessage(new ApiError(502, "ai_incomplete", "x"))).toMatch(/cut off/);
    expect(draftErrorMessage(new ApiError(422, "ai_invalid_draft", "x"))).toMatch(/couldn't turn/);
    expect(draftErrorMessage(new ApiError(503, "ai_rate_limited", "x"))).toMatch(/busy/);
    expect(draftErrorMessage(new ApiError(502, "ai_unavailable", "x"))).toMatch(/couldn't be reached/);
    expect(draftErrorMessage(new ApiError(429, "http_error", "Too Many Attempts."))).toMatch(/drafting limit/);
    expect(draftErrorMessage(new Error("x"))).toMatch(/Something went wrong/);
  });
});
