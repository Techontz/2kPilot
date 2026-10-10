"use client";

import { useMemo } from "react";
import { useTheme } from "@/components/providers/ThemeProvider";

/** Reads a raw theme variable (see globals.css) so charts match the UI in light and dark. */
export function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return value || fallback;
}

export interface ChartColors {
  text: string;
  grid: string;
  border: string;
  accent: string;
  positive: string;
  negative: string;
  surface: string;
  tooltip: string;
  foreground: string;
}

export function chartColors(): ChartColors {
  return {
    text: token("fg-subtle", "#6b7486"),
    grid: token("border", "#222a36"),
    border: token("line-strong", "#2e3847"),
    accent: token("brand-ink", "#c8a2f0"),
    positive: token("positive", "#34c28a"),
    negative: token("negative", "#ef5f6b"),
    surface: token("card", "#10141b"),
    tooltip: token("popover", "#161b24"),
    foreground: token("foreground", "#e7eaf0"),
  };
}

/** Theme colours that update when the user switches light/dark. */
export function useChartColors(): ChartColors & { theme: "light" | "dark" } {
  const { resolved } = useTheme();
  return useMemo(() => ({ ...chartColors(), theme: resolved }), [resolved]);
}
