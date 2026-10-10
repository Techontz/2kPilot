"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";

/**
 * Abstract cover artwork for strategies and accounts — a stylised chart motif
 * on a one-hue background (2K purple shades or graphite), picked
 * deterministically from the name so a strategy always gets the same cover.
 * Covers differ by motif and shade, never by hue. Decorative only
 * (aria-hidden): the name is always shown as text next to it.
 *
 * Never green (profit) or red (loss / LIVE real money).
 */
const PALETTES: [string, string][] = [
  ["#9e4fe0", "#5a1389"],
  ["#2e2e31", "#0e0e10"],
  ["#7b34c9", "#33094f"],
  ["#a66be6", "#6c25b0"],
  ["#3c3c40", "#18181a"],
  ["#5a1389", "#1d0533"],
];

export type Motif = "breakout" | "crossover" | "reversion" | "momentum" | "trend" | "candles" | "pulse";

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return Math.abs(h);
}

/** Pick a motif from the strategy's name/description (presentation only). */
export function motifFor(text: string): Motif {
  const t = text.toLowerCase();
  if (t.includes("breakout") || t.includes("highest high")) return "breakout";
  if (t.includes("bollinger") || t.includes("rsi") || t.includes("reversion")) return "reversion";
  if (t.includes("macd") || t.includes("momentum")) return "momentum";
  if (t.includes("crossover") || t.includes("cross")) return "crossover";
  if (t.includes("trend") || t.includes("moving")) return "trend";
  if (t.includes("candle")) return "pulse";
  return "candles";
}

function MotifShapes({ motif }: { motif: Motif }) {
  const line = { stroke: "white", strokeWidth: 3, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  switch (motif) {
    case "breakout":
      return (
        <>
          <rect x="14" y="40" width="46" height="26" rx="3" fill="white" fillOpacity="0.12" stroke="white" strokeOpacity="0.55" strokeWidth="1.5" strokeDasharray="3 3" />
          <path d="M10 60 L20 50 L28 58 L36 46 L44 56 L54 44 L64 34 L74 26 L88 14" {...line} />
          <circle cx="88" cy="14" r="4" fill="white" />
        </>
      );
    case "crossover":
      return (
        <>
          <path d="M8 70 C 30 66, 40 30, 92 26" {...line} />
          <path d="M8 40 C 30 44, 54 70, 92 62" {...line} strokeOpacity="0.55" />
          <circle cx="44" cy="52" r="5" fill="white" />
        </>
      );
    case "reversion":
      return (
        <>
          <path d="M6 30 C 30 22, 70 22, 94 30" {...line} strokeWidth={1.5} strokeOpacity="0.5" strokeDasharray="4 4" />
          <path d="M6 72 C 30 80, 70 80, 94 72" {...line} strokeWidth={1.5} strokeOpacity="0.5" strokeDasharray="4 4" />
          <path d="M6 52 C 16 30, 24 30, 32 52 S 48 74, 56 52 S 72 30, 80 52 S 90 66, 94 58" {...line} />
        </>
      );
    case "momentum":
      return (
        <>
          {[12, 22, 32, 42, 52, 62, 72, 82].map((x, i) => {
            const h = [8, 14, 20, 12, -6, -14, 10, 22][i]!;
            return <rect key={x} x={x} y={h > 0 ? 70 - h : 70} width="6" height={Math.abs(h)} rx="1.5" fill="white" fillOpacity={h > 0 ? 0.85 : 0.4} />;
          })}
          <path d="M8 46 C 28 30, 40 24, 52 40 S 76 44, 92 22" {...line} />
        </>
      );
    case "trend":
      return (
        <>
          <path d="M8 76 C 30 70, 50 50, 92 22" {...line} strokeWidth={8} strokeOpacity="0.18" />
          <path d="M8 74 L 22 64 L 30 68 L 44 52 L 54 56 L 68 38 L 78 42 L 92 24" {...line} />
        </>
      );
    case "pulse":
      return <path d="M6 54 H 30 L 38 30 L 48 76 L 58 40 L 64 54 H 94" {...line} />;
    default:
      return (
        <>
          {[18, 34, 50, 66, 82].map((x, i) => {
            const top = [48, 36, 44, 26, 18][i]!;
            const h = [18, 22, 14, 26, 20][i]!;
            return (
              <g key={x}>
                <line x1={x} x2={x} y1={top - 8} y2={top + h + 8} stroke="white" strokeOpacity="0.6" strokeWidth="1.5" />
                <rect x={x - 5} y={top} width="10" height={h} rx="2" fill="white" fillOpacity={i % 2 ? 0.95 : 0.45} />
              </g>
            );
          })}
        </>
      );
  }
}

export function Artwork({ seed, motif, className, rounded = "rounded-md" }: { seed: string; motif?: Motif; className?: string; rounded?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [a, b] = PALETTES[hash(seed) % PALETTES.length]!;
  const m = motif ?? motifFor(seed);
  return (
    <div aria-hidden className={cn("relative overflow-hidden", rounded, className)} style={{ background: `linear-gradient(135deg, ${a}, ${b})` }}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 size-full">
        <defs>
          <radialGradient id={`${id}-shine`} cx="20%" cy="0%" r="90%">
            <stop offset="0%" stopColor="white" stopOpacity="0.32" />
            <stop offset="60%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <pattern id={`${id}-grid`} width="10" height="10" patternUnits="userSpaceOnUse">
            <path d="M10 0H0V10" fill="none" stroke="white" strokeOpacity="0.08" strokeWidth="0.6" />
          </pattern>
        </defs>
        <rect width="100" height="100" fill={`url(#${id}-grid)`} />
        <rect width="100" height="100" fill={`url(#${id}-shine)`} />
        <MotifShapes motif={m} />
      </svg>
    </div>
  );
}

/** A balance trend drawn as cover art (account hero). Falls back to the brand motif. */
export function SeriesArtwork({ values, tone, className }: { values: number[]; tone: "live" | "demo" | "paper"; className?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const bg = tone === "live" ? "linear-gradient(160deg, #d6392e, #8a1a14)" : tone === "demo" ? "linear-gradient(160deg, #9e4fe0, #5a1389)" : "linear-gradient(160deg, #3c3c40, #141416)";
  const usable = values.length > 1 && new Set(values).size > 1;
  let path = "M8 74 C 28 72, 36 52, 52 54 S 74 36, 92 20";
  if (usable) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    path = values.map((v, i) => `${i ? "L" : "M"}${(8 + (i / (values.length - 1)) * 84).toFixed(1)} ${(80 - ((v - min) / (max - min)) * 60).toFixed(1)}`).join(" ");
  }
  return (
    <div aria-hidden className={cn("relative overflow-hidden", className)} style={{ background: bg }}>
      <svg viewBox="0 0 100 100" className="absolute inset-0 size-full">
        <defs>
          <radialGradient id={`${id}-s`} cx="15%" cy="0%" r="95%">
            <stop offset="0%" stopColor="white" stopOpacity="0.35" />
            <stop offset="65%" stopColor="white" stopOpacity="0" />
          </radialGradient>
          <linearGradient id={`${id}-f`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="white" stopOpacity="0.35" />
            <stop offset="100%" stopColor="white" stopOpacity="0" />
          </linearGradient>
        </defs>
        <rect width="100" height="100" fill={`url(#${id}-s)`} />
        <path d={`${path} L92 100 L8 100 Z`} fill={`url(#${id}-f)`} />
        <path d={path} fill="none" stroke="white" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}
