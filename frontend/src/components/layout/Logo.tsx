import Image from "next/image";
import { cn } from "@/lib/utils";

type Size = "sm" | "md" | "lg";

const TILE: Record<Size, string> = {
  sm: "size-8 rounded-[9px]",
  md: "size-9 rounded-[10px]",
  lg: "size-11 rounded-xl",
};
const WORD: Record<Size, string> = {
  sm: "text-[19px]",
  md: "text-[21px]",
  lg: "text-[26px]",
};

/** The 2K app tile alone (same family icon as 2kTunes). */
export function LogoMark({ className, size = "md", preload = false }: { className?: string; size?: Size; preload?: boolean }) {
  return (
    <Image
      src="/brand/icon-192.png"
      alt="2kPilot"
      width={48}
      height={48}
      preload={preload}
      className={cn("shrink-0 select-none", TILE[size], className)}
      draggable={false}
    />
  );
}

/**
 * 2kPilot lockup: the 2K tile + wordmark — "2k" in the foreground colour and
 * "Pilot" in the brand purple (lavender on dark). `tone="onDark"` pins the
 * dark-surface colours regardless of theme (auth screens).
 */
export function Logo({
  wordmark = true,
  className,
  size = "md",
  tone = "auto",
  preload = false,
}: {
  wordmark?: boolean;
  className?: string;
  size?: Size;
  tone?: "auto" | "onDark";
  preload?: boolean;
}) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark size={size} preload={preload} className={tone === "onDark" ? "shadow-[0_6px_20px_-6px_rgb(158_79_224/0.7)]" : "shadow-[0_4px_14px_-6px_rgb(110_40_180/0.55)]"} />
      {wordmark && (
        <span aria-hidden className={cn("leading-none font-black tracking-[-0.04em]", WORD[size], tone === "onDark" ? "text-white" : "text-fg")}>
          2k<span className={tone === "onDark" ? "text-[#C8A2F0]" : "text-brand-ink"}>Pilot</span>
        </span>
      )}
    </span>
  );
}
