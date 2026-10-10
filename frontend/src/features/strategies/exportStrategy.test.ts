import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { exportFileName, exportStrategy, strategySlug } from "./exportStrategy";

describe("strategySlug", () => {
  it("makes safe file names", () => {
    expect(strategySlug("My EMA cross!")).toBe("my-ema-cross");
    expect(strategySlug("  Ünïcode — test  ")).toBe("unicode-test");
    expect(strategySlug("!!!")).toBe("strategy");
    expect(exportFileName("Breakout")).toBe("breakout.tradepilot.json");
  });
});

describe("exportStrategy", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("downloads <slug>.tradepilot.json", async () => {
    fetchMock.mockResolvedValue(new Response('{"format":"tradepilot.strategy"}', { status: 200, headers: { "Content-Type": "application/json" } }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    let downloaded = "";
    click.mockImplementation(function (this: HTMLAnchorElement) {
      downloaded = this.download;
    });
    await exportStrategy({ id: "s-1", name: "My EMA cross" });
    expect(String(fetchMock.mock.calls[0]![0])).toBe("/api/strategies/s-1/export");
    expect(fetchMock.mock.calls[0]![1]).toMatchObject({ credentials: "same-origin" });
    expect(downloaded).toBe("my-ema-cross.tradepilot.json");
    click.mockRestore();
  });

  it("throws an ApiError with the server's message", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ message: "Only rule-based strategies can be exported.", code: "not_exportable" }), { status: 422 }));
    const err = await exportStrategy({ id: "s-2", name: "Code" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 422, code: "not_exportable", message: "Only rule-based strategies can be exported." });
  });
});
