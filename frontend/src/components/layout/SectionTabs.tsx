"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect, useRef } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface SectionTab {
  value: string;
  label: string;
  content: ReactNode;
}

/** Resolve `?tab=` against the known tabs (unknown or missing → the first tab). */
export function resolveTab(tabs: readonly { value: string }[], requested: string | null): string {
  return tabs.some((t) => t.value === requested) ? requested! : (tabs[0]?.value ?? "");
}

/**
 * Tabs inside one of the four sections, kept in the URL (`?tab=…`) so links,
 * redirects from old pages and the back button all work. Only the active tab
 * is mounted, so hidden tabs do not poll.
 */
export function SectionTabs({ title, description, tabs, actions }: { title: string; description?: ReactNode; tabs: SectionTab[]; actions?: ReactNode }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const active = resolveTab(tabs, params.get("tab"));
  const chips = useRef<HTMLDivElement>(null);

  // Phones: keep the active chip visible in the sideways-scrolling row (e.g. after a link to ?tab=security).
  useEffect(() => {
    const box = chips.current;
    const chip = box?.querySelector<HTMLElement>('[data-state="active"]');
    if (!box || !chip || box.scrollWidth <= box.clientWidth) return;
    if (chip.offsetLeft >= box.scrollLeft && chip.offsetLeft + chip.offsetWidth <= box.scrollLeft + box.clientWidth) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    box.scrollTo?.({ left: Math.max(0, chip.offsetLeft - 16), behavior: reduce ? "auto" : "smooth" });
  }, [active]);

  const select = (value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value === tabs[0]?.value) next.delete("tab");
    else next.set("tab", value);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  return (
    <Tabs value={active} onValueChange={select} className="gap-6 sm:gap-7">
      <div className="flex flex-col gap-5 sm:gap-6">
        <div className="flex flex-wrap items-end justify-between gap-4 pt-1 sm:pt-6">
          <div className="min-w-0 motion-safe:animate-fade-up">
            <h1 className="title-xl text-[2.5rem] text-fg sm:text-5xl lg:text-6xl">{title}</h1>
            {description && <p className="mt-2.5 max-w-2xl text-[15px] leading-relaxed text-fg-muted sm:mt-3">{description}</p>}
          </div>
          {actions && <div className="flex w-full items-center gap-2 sm:w-auto [&>*]:max-sm:flex-1">{actions}</div>}
        </div>
        {/* Scrolls sideways on narrow screens instead of widening the page. */}
        <div ref={chips} className="no-scrollbar relative -mx-4 snap-x scroll-px-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <TabsList className="h-9 group-data-horizontal/tabs:h-9 max-sm:h-11 max-sm:group-data-horizontal/tabs:h-11">
            {tabs.map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="flex-none snap-start px-4 max-sm:px-5 max-sm:text-[15px]">
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </div>
      {tabs.map((t) => (
        <TabsContent key={t.value} value={t.value} className="min-w-0 motion-safe:animate-fade-in">
          {t.value === active ? t.content : null}
        </TabsContent>
      ))}
    </Tabs>
  );
}
