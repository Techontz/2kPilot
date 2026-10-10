import { describe, expect, it } from "vitest";
import { safeNext } from "./LoginForm";

describe("safeNext", () => {
  it("keeps same-site paths with query and hash", () => {
    expect(safeNext("/history?tab=closed#top")).toBe("/history?tab=closed#top");
    expect(safeNext("/settings")).toBe("/settings");
  });

  it.each([null, "", "history", "https://evil.com", "//evil.com", "/\\evil.com", "/%0d/evil.com\n", "/\tevil"])(
    "falls back to / for %j",
    (next) => {
      expect(safeNext(next)).toBe("/");
    },
  );
});
