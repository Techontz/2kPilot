import { afterEach, describe, expect, it, vi } from "vitest";
import { applyTheme, readThemePreference, resolveTheme, THEME_STORAGE_KEY, writeThemePreference } from "./theme";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("theme", () => {
  it("defaults to the system preference", () => {
    expect(readThemePreference()).toBe("system");
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
  });

  it("persists the choice and ignores junk", () => {
    writeThemePreference("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(readThemePreference()).toBe("dark");
    window.localStorage.setItem(THEME_STORAGE_KEY, "purple");
    expect(readThemePreference()).toBe("system");
  });

  it("survives blocked storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(readThemePreference()).toBe("system");
    expect(() => writeThemePreference("light")).not.toThrow();
  });

  it("toggles the dark class on <html>", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
