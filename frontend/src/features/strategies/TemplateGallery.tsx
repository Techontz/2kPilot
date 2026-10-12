"use client";

import { ChevronRight, Copy, FlaskConical, LayoutTemplate } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Artwork } from "@/components/app/artwork";
import { DifficultyBadge } from "@/components/app/badges";
import { CardsSkeleton, EmptyState, ErrorState } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api, ApiError } from "@/lib/api";
import { contractSummary } from "@/lib/contracts";
import type { Strategy } from "@/lib/types";
import type { StrategyActions } from "./StrategiesSection";
import { StrategyInsights } from "./StrategyInsights";
import { strategyTimeframe, uniqueName } from "./strategyUtils";

const LEVEL_ORDER: Record<string, number> = { beginner: 0, intermediate: 1, advanced: 2 };

interface Loaded {
  data: Strategy[] | null;
  error: string | null;
  reload: () => Promise<unknown>;
}

/**
 * Built-in templates as compact cards (cover, name, difficulty, one line, actions).
 * The full explanation — how it works, when it struggles, markets and the
 * educational disclaimer — lives in the detail sheet.
 */
export function TemplateGallery({ strategies, actions }: { strategies: Loaded; actions: StrategyActions }) {
  const router = useRouter();
  const [copying, setCopying] = useState<string | null>(null);
  const [open, setOpen] = useState<Strategy | null>(null);
  if (!strategies.data) return strategies.error ? <ErrorState message={strategies.error} onRetry={() => void strategies.reload()} /> : <CardsSkeleton />;
  const templates = strategies.data.filter((s) => s.built_in)
    .sort((a, b) => (LEVEL_ORDER[a.details?.difficulty ?? ""] ?? 3) - (LEVEL_ORDER[b.details?.difficulty ?? ""] ?? 3) || a.name.localeCompare(b.name));
  if (templates.length === 0) {
    return <Card><EmptyState icon={LayoutTemplate} title="No templates available">The server has no built-in templates yet. Ask the administrator to run the database migrations.</EmptyState></Card>;
  }

  const use = async (t: Strategy) => {
    setCopying(t.id);
    try {
      const name = uniqueName(t.name, strategies.data!.filter((s) => !s.built_in).map((s) => s.name));
      const copy = await api<Strategy>(`/strategies/${t.id}/copy`, { method: "POST", body: { name } });
      toast.success(`“${name}” is now in My strategies`, { description: "Review the rules, test it, then activate it." });
      actions.reload();
      router.push(t.key === "rules" ? `/strategies/${copy.id}/edit` : "/strategies?tab=mine");
    } catch (e) {
      toast.error("Couldn't copy the template", { description: e instanceof ApiError ? e.message : undefined });
    } finally {
      setCopying(null);
    }
  };

  return (
    <div className="space-y-5">
      <section aria-labelledby="library-heading">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 id="library-heading" className="text-xl font-extrabold tracking-tight text-fg sm:text-2xl">
            Template library<span className="ml-2 text-sm font-semibold text-fg-subtle">{templates.length}</span>
          </h2>
          <p className="text-xs text-fg-subtle">Learning starting points — none is claimed to be profitable.</p>
        </div>
        <ul className="grid grid-cols-1 gap-3 min-[560px]:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {templates.map((t) => (
            <li key={t.id}>
              <Card className="group/tpl h-full gap-0 py-0 transition-colors hover:bg-surface-hover">
                <button type="button" onClick={() => setOpen(t)} aria-label={`About the ${t.name} template`}
                  className="flex w-full items-center gap-3.5 rounded-t-xl p-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 min-[560px]:flex-col min-[560px]:items-stretch">
                  <Artwork seed={`${t.name} ${t.description}`} className="size-16 shrink-0 shadow-raised min-[560px]:aspect-[16/9] min-[560px]:size-auto min-[560px]:w-full" />
                  <span className="min-w-0 flex-1 min-[560px]:px-0.5">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-[15px] font-extrabold tracking-tight text-fg">{t.name}</span>
                      <ChevronRight aria-hidden className="ml-auto size-4 shrink-0 text-fg-subtle transition-transform group-hover/tpl:translate-x-0.5" />
                    </span>
                    <span className="mt-0.5 block truncate text-[13px] text-fg-muted">{t.description}</span>
                    <span className="mt-2 flex items-center gap-2">
                      <DifficultyBadge level={t.details?.difficulty} />
                      <span className="truncate text-xs text-fg-subtle">{strategyTimeframe(t)} candles</span>
                    </span>
                  </span>
                </button>
                <div className="mt-auto flex gap-2 border-t border-line px-3 py-2.5">
                  <Button size="sm" variant="secondary" onClick={() => void use(t)} disabled={copying !== null} aria-label={`Use the ${t.name} template`} className="flex-1 min-[560px]:flex-none">
                    <Copy aria-hidden /> {copying === t.id ? "Copying…" : "Use"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => actions.test(t)} aria-label={`Test the ${t.name} template`}><FlaskConical aria-hidden /> Test</Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      </section>
      <TemplateSheet template={open} onClose={() => setOpen(null)} copying={copying} onUse={(t) => void use(t)} onTest={(t) => { setOpen(null); actions.test(t); }} onChanged={actions.reload} />
    </div>
  );
}

function TemplateSheet({ template: t, onClose, copying, onUse, onTest, onChanged }: {
  template: Strategy | null;
  onChanged?: () => void;
  onClose: () => void;
  copying: string | null;
  onUse: (t: Strategy) => void;
  onTest: (t: Strategy) => void;
}) {
  const d = t?.details ?? {};
  return (
    <Sheet open={t !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="gap-0 overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-md">
        {t && (
          <>
            <SheetHeader className="gap-3 p-5 pt-12 pb-4">
              <Artwork seed={`${t.name} ${t.description}`} className="aspect-[16/9] w-full shadow-raised max-sm:aspect-[5/2]" />
              <div className="flex items-center gap-2 pt-1"><DifficultyBadge level={d.difficulty} /><span className="eyebrow text-fg-subtle">Template</span></div>
              <SheetTitle className="text-2xl font-extrabold">{t.name}</SheetTitle>
              <SheetDescription>{t.description}</SheetDescription>
            </SheetHeader>
            <div className="space-y-5 px-5 pb-4 text-sm">
              {d.how_it_works && (
                <section>
                  <h3 className="eyebrow text-fg-subtle">How it works</h3>
                  <p className="mt-1.5 leading-relaxed text-fg">{d.how_it_works}</p>
                </section>
              )}
              {d.struggles && (
                <section>
                  <h3 className="eyebrow text-fg-subtle">When it struggles</h3>
                  <p className="mt-1.5 leading-relaxed text-fg-muted">{d.struggles}</p>
                </section>
              )}
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-lg bg-surface-raised p-4 text-[13px]">
                <dt className="text-fg-subtle">Candles</dt><dd className="font-semibold text-fg">{strategyTimeframe(t)}</dd>
                {d.suggested_symbols?.length ? <><dt className="text-fg-subtle">Markets</dt><dd className="font-semibold break-words text-fg">{d.suggested_symbols.join(", ")}</dd></> : null}
                {d.suggested_contract && <><dt className="text-fg-subtle">Contract</dt><dd className="font-semibold text-fg">{contractSummary({ ...d.suggested_contract }).replace(/ · stake from risk profile$/, "")}</dd></>}
              </dl>
              {t.key !== "rules" && <StrategyInsights strategy={t} onChanged={onChanged} />}
              {d.suggested_contract_note && <p className="text-xs text-fg-muted">{d.suggested_contract_note}</p>}
              <p role="note" className="rounded-lg border border-line p-3 text-xs leading-relaxed text-fg-muted">
                {d.disclaimer ?? "Educational template — not a recommendation. No strategy is claimed to be profitable; test it on history and run it on a demo account first."}
              </p>
            </div>
            <SheetFooter className="flex-row gap-2 border-t border-line p-4 max-sm:pb-[calc(1rem+env(safe-area-inset-bottom))]">
              <Button className="flex-1" onClick={() => onUse(t)} disabled={copying !== null}>
                <Copy aria-hidden /> {copying === t.id ? "Copying…" : "Use this template"}
              </Button>
              <Button variant="outline" onClick={() => onTest(t)}><FlaskConical aria-hidden /> Test</Button>
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
