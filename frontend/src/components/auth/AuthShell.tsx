import { CircleStop, Gauge, ShieldCheck } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { Logo } from "@/components/layout/Logo";
import { AuthBackground } from "./AuthBackground";

const TRUST = [
  { icon: ShieldCheck, title: "Demo by default" },
  { icon: Gauge, title: "Limits checked on every trade" },
  { icon: CircleStop, title: "Stop anytime" },
];

const RISK_NOTE = "Trading involves risk of loss. 2kPilot makes no claim that any strategy is profitable.";

/**
 * Auth screens are dark-only and branded: true neutrals plus one 2K purple.
 * These override the app tokens inside the shell only.
 */
const AUTH_TOKENS = {
  "--primary": "#8b3fd9", // 2K purple, AA with white text
  "--primary-foreground": "#ffffff",
  "--ring": "#b57cf0",
  "--background": "#0e0e10",
  "--card": "#161618",
} as CSSProperties;

/** 2kPilot lockup on the dark auth backdrop (the shared app logo, dark tone). */
export function AuthLogo({ className, compact = false }: { className?: string; compact?: boolean }) {
  return <Logo tone="onDark" size={compact ? "sm" : "md"} preload className={className} />;
}

/**
 * Full-height, never-scrolling frame for sign-in and sign-up: a cinematic
 * background behind everything, a compact brand column (desktop) and the form
 * on a floating glass card. If content ever outgrows the viewport (tiny
 * phones, many errors) only the card scrolls — never the page.
 */
export function AuthShell({ children, footer }: { children: ReactNode; footer: ReactNode }) {
  return (
    <main style={AUTH_TOKENS} className="dark relative isolate h-dvh overflow-hidden bg-[#050507] text-white">
      <AuthBackground className="absolute inset-0 -z-20" />
      {/* Legibility scrims: darken behind the brand copy (left/bottom) and the form (right). */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 bg-[linear-gradient(180deg,rgb(5_5_7/0.55),rgb(5_5_7/0.2)_30%,rgb(5_5_7/0.75))] lg:bg-[linear-gradient(90deg,rgb(5_5_7/0.82),rgb(5_5_7/0.35)_45%,rgb(5_5_7/0.15)_60%,rgb(5_5_7/0.6))]" />

      <div className="mx-auto grid h-full w-full max-w-[1480px] grid-rows-[auto_minmax(0,1fr)] px-4 sm:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(400px,452px)] lg:grid-rows-1 lg:gap-[clamp(2.5rem,6vw,7rem)] lg:px-[clamp(2rem,4.5vw,5rem)]">
        <BrandPanel />
        <MobileBrand />

        <section className="flex min-h-0 items-start justify-center pb-4 sm:items-center lg:py-[clamp(1rem,4vh,3rem)] short:lg:py-3">
          <div className="max-h-full w-full max-w-[440px] overflow-y-auto overscroll-contain rounded-2xl bg-[#0e0e10]/80 p-5 shadow-[0_40px_120px_-30px_rgb(0_0_0/0.9)] ring-1 ring-white/10 backdrop-blur-xl [scrollbar-width:thin] motion-safe:animate-fade-up sm:p-8 short:px-6 short:py-5 tiny:py-4 lg:max-w-none">
            {children}
            <div className="mt-6 border-t border-white/10 pt-5 text-center text-sm text-white/65 short:mt-4 short:pt-3 tiny:mt-3 tiny:pt-2.5">{footer}</div>
            <p className="mt-3 text-center text-[11px] leading-snug text-white/55 lg:hidden">{RISK_NOTE}</p>
          </div>
        </section>
      </div>
    </main>
  );
}

function MobileBrand() {
  return (
    <header className="flex items-center justify-between gap-3 pt-[max(1rem,env(safe-area-inset-top))] pb-4 sm:pt-8 sm:pb-6 lg:hidden">
      <AuthLogo compact />
      <p className="truncate text-[13px] font-semibold text-white/70">Set the rules. We fly the trades.</p>
    </header>
  );
}

function BrandPanel() {
  return (
    <aside className="hidden min-h-0 flex-col py-[clamp(1.25rem,4.5vh,3rem)] lg:flex">
      <AuthLogo />

      <div className="my-auto max-w-[640px] py-6">
        <p className="eyebrow text-[#C8A2F0]">Autopilot for trading</p>
        <h2 className="mt-3 text-[clamp(2rem,min(3.3vw,5.8vh),3.5rem)] leading-[1.02] font-black tracking-[-0.04em] text-white">
          Set the rules.<br />
          <span className="text-white/55">2kPilot flies the trades.</span>
        </h2>
        <p className="mt-3 text-[clamp(0.875rem,1.9vh,1rem)] leading-snug text-white/70">
          Build rules, test them on past prices, run them on demo — within your limits.
        </p>

        <FlightDeck />

        <ul className="mt-[clamp(1rem,3vh,1.75rem)] flex flex-wrap gap-2">
          {TRUST.map(({ icon: Icon, title }) => (
            <li key={title} className="flex items-center gap-1.5 rounded-full bg-white/[0.06] px-3 py-1.5 text-xs font-semibold text-white/85 ring-1 ring-white/10 backdrop-blur-md">
              <Icon className="size-3.5 text-[#C8A2F0]" aria-hidden /> {title}
            </li>
          ))}
        </ul>
      </div>

      <p className="max-w-[560px] text-[11px] leading-relaxed text-white/50">{RISK_NOTE} Past or simulated results don&apos;t guarantee future ones.</p>
    </aside>
  );
}

/** Compact "instrument" card: monochrome candles and an equity line that draws itself once. */
function FlightDeck() {
  const candles = [
    [20, 62, 72, 56, 78, false], [44, 68, 58, 52, 74, true], [68, 60, 64, 56, 70, false], [92, 62, 52, 46, 66, true],
    [116, 54, 47, 41, 58, true], [140, 48, 55, 44, 60, false], [164, 54, 43, 37, 58, true], [188, 44, 36, 30, 48, true],
    [212, 38, 42, 34, 47, false], [236, 40, 31, 26, 44, true], [260, 32, 25, 20, 36, true], [284, 27, 20, 15, 31, true],
  ] as const;
  return (
    <div aria-hidden className="mt-[clamp(1rem,3.5vh,2rem)] w-full max-w-[400px] motion-safe:animate-float">
      <div className="rounded-xl bg-[#0e0e10]/70 p-4 shadow-[0_30px_80px_-24px_rgb(0_0_0/0.85)] ring-1 ring-white/10 backdrop-blur-md">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold text-white/55">Paper account · R_100</p>
            <p className="num mt-0.5 text-xl font-extrabold tracking-tight text-white">$10,482.60</p>
          </div>
          <span className="flex items-center gap-1.5 rounded-full bg-white/[0.08] px-2.5 py-1 text-[11px] font-bold text-white/90">
            <span className="relative flex size-1.5"><span className="absolute inset-0 rounded-full bg-[#C8A2F0] motion-safe:animate-pulse-ring" /><span className="relative size-1.5 rounded-full bg-[#C8A2F0]" /></span>
            Bot running
          </span>
        </div>
        <svg viewBox="0 0 304 84" className="mt-3 h-[clamp(52px,9vh,84px)] w-full" preserveAspectRatio="none">
          <defs>
            <linearGradient id="tp-auth-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#9E4FE0" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#9E4FE0" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[21, 42, 63].map((y) => <line key={y} x1="0" x2="304" y1={y} y2={y} stroke="white" strokeOpacity="0.07" strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />)}
          {candles.map(([x, open, close, high, low, up]) => (
            <g key={x} opacity={up ? 0.5 : 0.3}>
              <line x1={x} x2={x} y1={high} y2={low} stroke="white" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
              <rect x={x - 4.5} y={Math.min(open, close)} width="9" height={Math.max(2, Math.abs(open - close))} rx="1.5" fill={up ? "white" : "none"} stroke="white" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            </g>
          ))}
          <path d="M0 74 C 30 71, 50 64, 76 66 S 120 54, 150 51 S 200 43, 226 34 S 270 20, 304 15 L304 84 L0 84 Z" fill="url(#tp-auth-fill)" />
          <path d="M0 74 C 30 71, 50 64, 76 66 S 120 54, 150 51 S 200 43, 226 34 S 270 20, 304 15" fill="none" stroke="#C8A2F0" strokeWidth="2.25" strokeLinecap="round"
            strokeDasharray="420" className="motion-safe:animate-draw [--tp-dash:420]" />
        </svg>
        <div className="mt-3 flex flex-wrap gap-1.5 text-[10.5px] font-semibold text-white/70">
          <span className="rounded-full bg-white/[0.06] px-2 py-0.5 ring-1 ring-white/10">✓ Risk check passed</span>
          <span className="rounded-full bg-white/[0.06] px-2 py-0.5 ring-1 ring-white/10">Rise/Fall · 5 min</span>
          <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-white ring-1 ring-white/20">DEMO</span>
        </div>
      </div>
      <p className="mt-1.5 text-[11px] text-white/45">Illustration — not real results.</p>
    </div>
  );
}
