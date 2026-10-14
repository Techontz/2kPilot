import { describe, expect, it } from "vitest";
import type { Strategy } from "@/lib/types";
import { buildParameters, changedKeys, initialValues, paramFields } from "./paramForm";

const strategy = {
  id: "s-1",
  key: "adaptive_trend_momentum",
  parameter_schema: {
    properties: {
      entry_timeframe: { $ref: "#/$defs/Timeframe", default: "M5", description: "Timeframe used for entries." },
      min_adx: { type: "number", title: "Min Adx", minimum: 5, maximum: 80, default: 25 },
      max_open_positions: { type: "integer", title: "Max Open Positions", minimum: 1, maximum: 50, default: 1 },
      rsi_mode: { type: "string", enum: ["cross", "rising"], default: "cross" },
      symbols: { type: "array" },
    },
    $defs: { Timeframe: { enum: ["M1", "M5", "M15"] } },
  },
  versions: [{ id: "v-1", version: 1, parameters: { min_adx: 25, max_open_positions: 1, rsi_mode: "cross", entry_timeframe: "M5", extra: "kept" } }],
} as unknown as Strategy;

describe("strategy parameter form", () => {
  it("builds fields from the schema, the important trading settings first", () => {
    const fields = paramFields(strategy);
    expect(fields.map((f) => f.key)).toEqual(["max_open_positions", "min_adx", "entry_timeframe", "rsi_mode"]);
    expect(fields[0]).toMatchObject({ label: "Trades open at once (max)", kind: "integer", min: 1, max: 50, group: "trading" });
    expect(fields.find((f) => f.key === "entry_timeframe")).toMatchObject({ kind: "choice", options: ["M1", "M5", "M15"] });
  });

  it("starts from the latest version and keeps settings the form doesn't show", () => {
    const fields = paramFields(strategy);
    const values = { ...initialValues(strategy, fields), max_open_positions: "3", min_adx: "22.5" };
    const { parameters, errors } = buildParameters(strategy, fields, values);
    expect(errors).toEqual({});
    expect(parameters).toEqual({ min_adx: 22.5, max_open_positions: 3, rsi_mode: "cross", entry_timeframe: "M5", extra: "kept" });
    expect(changedKeys(strategy, parameters)).toEqual(["min_adx", "max_open_positions"]);
  });

  it("refuses values outside the limits", () => {
    const fields = paramFields(strategy);
    const base = initialValues(strategy, fields);
    const { errors } = buildParameters(strategy, fields, { ...base, max_open_positions: "2.5", min_adx: "90", rsi_mode: "fast" });
    expect(errors).toEqual({ max_open_positions: "Enter a whole number.", min_adx: "At most 80.", rsi_mode: "Choose one of the options." });
  });
});
