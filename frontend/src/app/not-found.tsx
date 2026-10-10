import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Logo } from "@/components/layout/Logo";

export default function NotFound() {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-5 text-center">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-96 bg-[linear-gradient(180deg,color-mix(in_oklab,var(--brand-1)_14%,transparent),transparent)]" />
      <Link href="/" aria-label="2kPilot home" className="absolute top-6 left-6 rounded-lg"><Logo /></Link>
      <svg aria-hidden viewBox="0 0 320 140" className="relative w-72 max-w-full sm:w-96" fill="none">
        <path d="M10 110 C 60 108, 80 70, 120 72 S 160 40, 190 46" className="stroke-primary" strokeWidth="4" strokeLinecap="round" />
        <path d="M190 46 C 214 50, 236 90, 268 96" className="stroke-fg-subtle" strokeWidth="3" strokeLinecap="round" strokeDasharray="2 9" />
        <circle cx="190" cy="46" r="7" className="fill-primary" />
        <circle cx="190" cy="46" r="16" className="fill-primary/15" />
        <text x="276" y="104" className="fill-fg-subtle text-[22px] font-extrabold">?</text>
      </svg>
      <p className="num relative mt-6 text-sm font-bold tracking-[0.2em] text-fg-subtle">404</p>
      <h1 className="title-xl relative mt-2 text-4xl text-fg sm:text-5xl">Off the flight path</h1>
      <p className="relative mt-3 max-w-sm text-sm text-fg-muted">This page doesn&apos;t exist or has moved. Your bot and your settings are unaffected.</p>
      <Link href="/" className="relative mt-8 inline-flex h-11 items-center gap-2 rounded-full bg-foreground px-6 text-sm font-bold text-background transition-transform hover:scale-[1.03]">
        <ArrowLeft className="size-4" aria-hidden /> Back to Overview
      </Link>
    </main>
  );
}
