"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "@/components/providers/ThemeProvider";
import { Button } from "@/components/ui/button";
import type { ThemePreference } from "@/lib/theme";

const NEXT: Record<ThemePreference, ThemePreference> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<ThemePreference, string> = { system: "System theme", light: "Light theme", dark: "Dark theme" };

/** Cycles System → Light → Dark. */
export function ThemeToggle({ className }: { className?: string }) {
  const { preference, setPreference } = useTheme();
  const Icon = preference === "light" ? Sun : preference === "dark" ? Moon : Monitor;
  return (
    <Button variant="ghost" size="icon-lg" className={className} onClick={() => setPreference(NEXT[preference])}
      aria-label={`${LABEL[preference]} — switch to ${LABEL[NEXT[preference]].toLowerCase()}`} title={LABEL[preference]}>
      <Icon aria-hidden />
    </Button>
  );
}
