"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import {
  applyTheme,
  readThemePreference,
  resolveTheme,
  type ResolvedTheme,
  systemPrefersDark,
  type ThemePreference,
  writeThemePreference,
} from "@/lib/theme";

interface ThemeValue {
  /** What the user picked ("system" by default). */
  preference: ThemePreference;
  /** What is actually shown. */
  resolved: ResolvedTheme;
  setPreference: (value: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Server render assumes "system"; the inline head script already painted the right theme.
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    typeof window === "undefined" ? "system" : readThemePreference(),
  );
  const preferenceRef = useRef(preference);
  useEffect(() => {
    preferenceRef.current = preference;
  }, [preference]);

  // The DOM class is updated *before* React re-renders, so anything that reads
  // computed colours during render (charts) sees the new theme immediately.
  const subscribeSystem = useCallback((onChange: () => void) => {
    try {
      const query = window.matchMedia("(prefers-color-scheme: dark)");
      const handler = () => {
        applyTheme(resolveTheme(preferenceRef.current, query.matches));
        onChange();
      };
      query.addEventListener("change", handler);
      return () => query.removeEventListener("change", handler);
    } catch {
      return () => undefined;
    }
  }, []);
  const prefersDark = useSyncExternalStore(subscribeSystem, systemPrefersDark, () => false);
  const resolved = resolveTheme(preference, prefersDark);

  // No mount effect: THEME_SCRIPT already set the DOM before paint, and during
  // hydration `prefersDark` is the server snapshot (false) — applying it would flash.

  const setPreference = useCallback((value: ThemePreference) => {
    applyTheme(resolveTheme(value, systemPrefersDark()));
    preferenceRef.current = value;
    setPreferenceState(value);
    writeThemePreference(value);
  }, []);

  const value = useMemo(() => ({ preference, resolved, setPreference }), [preference, resolved, setPreference]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
