"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
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

  const select = (value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value === tabs[0]?.value) next.delete("tab");
    else next.set("tab", value);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  return (
    <Tabs value={active} onValueChange={select} className="gap-7">
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-end justify-between gap-4 pt-2 sm:pt-6">
          <div className="min-w-0 motion-safe:animate-fade-up">
            <h1 className="title-xl text-4xl text-fg sm:text-5xl lg:text-6xl">{title}</h1>
            {description && <p className="mt-3 max-w-2xl text-sm leading-relaxed text-fg-muted sm:text-[15px]">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
        {/* Scrolls sideways on narrow screens instead of widening the page. */}
        <div className="-mx-4 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:px-0">
          <TabsList className="h-9 group-data-horizontal/tabs:h-9">
            {tabs.map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="flex-none px-4">
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
