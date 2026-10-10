"use client";

import { Plus } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SectionTabs } from "@/components/layout/SectionTabs";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/hooks";
import type { RulesCatalog, Strategy } from "@/lib/types";
import { ActivateDialog } from "./ActivateDialog";
import { AddStrategyDialog } from "./AddStrategyDialog";
import { BacktestDialog } from "./BacktestDialog";
import { BacktestsList } from "./BacktestsList";
import { MyStrategies } from "./MyStrategies";
import { TemplateGallery } from "./TemplateGallery";

export const STRATEGY_TABS = ["mine", "templates", "backtests"] as const;

export interface StrategyActions {
  activate: (s: Strategy) => void;
  test: (s: Strategy) => void;
  reload: () => void;
}

/**
 * STRATEGIES — my strategies, templates, and backtests. Dialogs for
 * Activate and "Test on history" live here so any card (and links like
 * /strategies?activate=<id> or ?test=<id> from the builder) can open them.
 */
export function StrategiesSection() {
  const strategies = useApi<Strategy[]>("/strategies", undefined, 20_000);
  const catalog = useApi<RulesCatalog>("/strategies/catalog");
  const [adding, setAdding] = useState(false);
  const [activating, setActivating] = useState<Strategy | null>(null);
  const [testing, setTesting] = useState<Strategy | null>(null);
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const reload = strategies.reload;

  // Deep links from the builder's success panel: ?activate=<id> / ?test=<id>.
  const wantActivate = params.get("activate");
  const wantTest = params.get("test");
  useEffect(() => {
    if (!strategies.data || (!wantActivate && !wantTest)) return;
    const find = (id: string | null) => (id ? strategies.data!.find((s) => s.id === id) ?? null : null);
    const a = find(wantActivate);
    const t = find(wantTest);
    const next = new URLSearchParams(params.toString());
    next.delete("activate");
    next.delete("test");
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    // Opening a dialog in response to the URL is an external sync, not derived state.
    queueMicrotask(() => {
      if (a) setActivating(a);
      if (t) setTesting(t);
    });
  }, [strategies.data, wantActivate, wantTest, params, pathname, router]);

  const actions: StrategyActions = {
    activate: setActivating,
    test: setTesting,
    reload: useCallback(() => void reload(), [reload]),
  };

  return (
    <>
      <SectionTabs
        title="Strategies"
        description="A strategy is a set of simple rules the bot follows. Test it on past prices, then activate it on a demo account."
        actions={<Button onClick={() => setAdding(true)}><Plus aria-hidden /> Add strategy</Button>}
        tabs={[
          { value: "mine", label: "My strategies", content: <MyStrategies strategies={strategies} actions={actions} onAdd={() => setAdding(true)} /> },
          { value: "templates", label: "Templates", content: <TemplateGallery strategies={strategies} actions={actions} /> },
          { value: "backtests", label: "Backtests", content: <BacktestsList strategies={strategies.data} onTest={setTesting} /> },
        ]}
      />
      <AddStrategyDialog open={adding} onOpenChange={setAdding} catalog={catalog.data ?? undefined} />
      <ActivateDialog strategy={activating} open={activating !== null} onOpenChange={(o) => !o && setActivating(null)} onDone={actions.reload} />
      <BacktestDialog strategy={testing} open={testing !== null} onOpenChange={(o) => !o && setTesting(null)} />
    </>
  );
}
