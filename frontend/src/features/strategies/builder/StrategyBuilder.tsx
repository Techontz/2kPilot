"use client";

import { ArrowLeft, CircleCheck, FlaskConical, Loader2, Power, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Notice } from "@/components/app/states";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import type { RulesCatalog, Strategy, StrategyVersion, Timeframe } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ContractExitNotes, StopTargetEditor } from "./ExitSection";
import { ConditionList, GroupCard } from "./GroupCard";
import {
  type BuilderState,
  type ConditionState,
  type GroupKey,
  type GroupState,
  NAME_MAX,
  defaultCondition,
  findProblems,
  indicatorOperand,
  mirrorCondition,
  previewLines,
  priceOperand,
  stateToRules,
  totalConditions,
  valueOperand,
} from "./model";

const TIMEFRAME_WORDS: Record<Timeframe, [string, string]> = {
  M1: ["Every minute", "1-minute"],
  M5: ["Every 5 minutes", "5-minute"],
  M15: ["Every 15 minutes", "15-minute"],
  M30: ["Every 30 minutes", "30-minute"],
  H1: ["Every hour", "1-hour"],
  H4: ["Every 4 hours", "4-hour"],
  D1: ["Every day", "daily"],
};

export function timeframeText(tf: Timeframe): string {
  const [, candle] = TIMEFRAME_WORDS[tf] ?? [tf, tf];
  return `Checked when each ${candle} candle closes`;
}

interface Saved {
  id: string;
  name: string;
  version: number | null;
  isNew: boolean;
}

interface Baseline {
  name: string;
  description: string;
  rules: string;
}

function baselineOf(state: BuilderState, catalog: RulesCatalog): Baseline {
  return { name: state.name.trim(), description: state.description.trim(), rules: JSON.stringify(stateToRules(state, catalog)) };
}

export interface StrategyBuilderProps {
  catalog: RulesCatalog;
  initial: BuilderState;
  /** Editing an existing strategy: saving adds a new version (and renames if needed). */
  strategy?: Pick<Strategy, "id" | "name" | "description">;
  /** How a NEW strategy was made: "ai" when it started from a plain-English draft. */
  source?: "builder" | "ai";
  /** Shown above the form (e.g. the AI draft review, or "Your copy of …"). */
  banner?: ReactNode;
}

/**
 * The visual strategy builder: WHEN (buy / sell conditions, filters) → THEN
 * (a proposal to the risk engine) → EXIT (stop, target, early exits), with a
 * live plain-English preview. Never saves on its own.
 */
export function StrategyBuilder({ catalog, initial, strategy, source = "builder", banner }: StrategyBuilderProps) {
  const router = useRouter();
  const uid = useId();
  const [state, setState] = useState<BuilderState>(initial);
  const [baseline, setBaseline] = useState<Baseline | null>(() => (strategy ? baselineOf(initial, catalog) : null));
  const [notes, setNotes] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [nameTouched, setNameTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [apiProblems, setApiProblems] = useState<string[]>([]);
  const [apiError, setApiError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [saved, setSaved] = useState<Saved | null>(null);
  const stash = useRef<Partial<Record<GroupKey, GroupState>>>({});
  const summaryRef = useRef<HTMLDivElement>(null);

  const problems = useMemo(() => findProblems(state, catalog), [state, catalog]);
  const lines = useMemo(() => previewLines(state, catalog), [state, catalog]);
  const byAt = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const p of problems) map.set(p.at, [...(map.get(p.at) ?? []), p.text]);
    return map;
  }, [problems]);
  const problemsFor = (at: string) => byAt.get(at) ?? [];

  const total = totalConditions(state);
  const max = catalog.limits.max_conditions;
  const canAdd = total < max;

  const current = baselineOf(state, catalog);
  const dirty = baseline ? current.name !== baseline.name || current.description !== baseline.description || current.rules !== baseline.rules : true;

  // Leaving with unsaved changes asks first (nothing is ever saved automatically).
  const guard = dirty && !saved && (strategy !== undefined || state.name.trim() !== "" || attempted);
  useEffect(() => {
    if (!guard) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [guard]);

  const patch = (p: Partial<BuilderState>) => setState((s) => ({ ...s, ...p }));

  const freshGroup = (key: GroupKey): GroupState => {
    const remaining = Math.max(1, max - total);
    const mirrorOf = key === "buy" ? state.sell : key === "sell" ? state.buy : null;
    if (mirrorOf && mirrorOf.conditions.length > 0) {
      return { mode: mirrorOf.mode, conditions: mirrorOf.conditions.slice(0, remaining).map(mirrorCondition) };
    }
    if (key === "closeBuy") return { mode: "any", conditions: [exitCondition("gt", 70)] };
    if (key === "closeSell") return { mode: "any", conditions: [exitCondition("lt", 30)] };
    const c = defaultCondition(catalog);
    return { mode: "all", conditions: [key === "sell" ? mirrorCondition(c) : c] };
  };

  const exitCondition = (op: "gt" | "lt", value: number): ConditionState => ({
    ...defaultCondition(catalog),
    left: indicatorOperand(catalog, "rsi"),
    op,
    right: valueOperand(catalog, value),
  });

  const filterCondition = (): ConditionState => ({
    ...defaultCondition(catalog),
    left: priceOperand(catalog, "close"),
    op: "gt",
    right: indicatorOperand(catalog, "sma", { period: 200 }),
  });

  const toggle = (key: GroupKey, on: boolean) => {
    if (on) {
      const restored = stash.current[key];
      delete stash.current[key];
      patch({ [key]: restored ?? freshGroup(key) });
      return;
    }
    const next: Partial<BuilderState> = { [key]: null };
    if (state[key]) stash.current[key] = state[key] ?? undefined;
    // An early exit needs its entry side: switch it off together.
    const linked: Partial<Record<GroupKey, GroupKey>> = { buy: "closeBuy", sell: "closeSell" };
    const exitKey = linked[key];
    if (exitKey && state[exitKey]) {
      stash.current[exitKey] = state[exitKey] ?? undefined;
      next[exitKey] = null;
    }
    patch(next);
  };

  const save = async () => {
    setAttempted(true);
    setApiProblems([]);
    setApiError(null);
    setFieldErrors({});
    if (problems.length > 0) {
      summaryRef.current?.focus();
      return;
    }
    const rules = stateToRules(state, catalog);
    const name = state.name.trim();
    const description = state.description.trim();
    setBusy(true);
    try {
      if (!strategy) {
        const created = await api<Strategy>("/strategies", { method: "POST", body: { name, description, rules, source } });
        setSaved({ id: created.id, name: created.name, version: created.latest_version?.version ?? 1, isNew: true });
        toast.success(`Saved “${created.name}”`);
        return;
      }
      const metaChanged = !baseline || name !== baseline.name || description !== baseline.description;
      const rulesChanged = !baseline || current.rules !== baseline.rules;
      if (!metaChanged && !rulesChanged) {
        toast.info("Nothing to save — you haven't changed anything yet.");
        return;
      }
      if (metaChanged) {
        await api<Strategy>(`/strategies/${strategy.id}`, { method: "PATCH", body: { name, description } });
        setBaseline((b) => ({ ...(b ?? current), name, description }));
      }
      let version: number | null = null;
      if (rulesChanged) {
        const v = await api<StrategyVersion>(`/strategies/${strategy.id}/versions`, { method: "POST", body: { rules, notes: notes.trim() } });
        version = v.version;
        setBaseline((b) => ({ ...(b ?? current), rules: current.rules }));
        setNotes("");
      }
      setSaved({ id: strategy.id, name, version, isNew: false });
      toast.success(version ? `Saved “${name}” as version ${version}` : `Saved “${name}”`);
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        setApiProblems(e.problems);
        setFieldErrors(e.fieldErrors);
        const shownElsewhere = e.problems.length > 0 || Boolean(e.fieldErrors.name) || Boolean(e.fieldErrors.description);
        if (!shownElsewhere) setApiError(e.fieldErrors.rules?.[0] ?? e.fieldErrors.notes?.[0] ?? e.message);
      } else {
        setApiError("Something went wrong. Please try again.");
      }
      summaryRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  if (saved) {
    return (
      <SavedPanel
        saved={saved}
        onKeepEditing={() => {
          if (saved.isNew) router.push(`/strategies/${saved.id}/edit`);
          else setSaved(null);
        }}
      />
    );
  }

  const nameErrors = [...(attempted || nameTouched ? problemsFor("name") : []), ...(fieldErrors.name ?? [])];
  const descErrors = [...problemsFor("description"), ...(fieldErrors.description ?? [])];
  const hasBuy = state.buy !== null;
  const hasSell = state.sell !== null;

  return (
    <div className="flex flex-col gap-6">
      {banner}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <form
          className="flex min-w-0 flex-col gap-8"
          noValidate
          // Saving is only ever an explicit press of the Save button (Enter in a field does nothing).
          onSubmit={(e) => e.preventDefault()}
          aria-label="Strategy rules"
        >
          {/* ── Name ─────────────────────────────────────── */}
          <section aria-labelledby={`${uid}-about`} className="flex flex-col gap-4">
            <h2 id={`${uid}-about`} className="text-xl font-extrabold tracking-tight text-fg">
              About this strategy
            </h2>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${uid}-name`} className="text-sm font-medium text-fg">
                Name <span className="text-fg-subtle">(required)</span>
              </label>
              <Input
                id={`${uid}-name`}
                value={state.name}
                maxLength={NAME_MAX + 20}
                placeholder="e.g. My EMA crossover"
                aria-invalid={nameErrors.length > 0 || undefined}
                aria-describedby={nameErrors.length ? `${uid}-name-err` : undefined}
                onBlur={() => setNameTouched(true)}
                onChange={(e) => patch({ name: e.target.value })}
                className="max-w-lg"
              />
              {nameErrors.length > 0 && (
                <p id={`${uid}-name-err`} className="text-sm text-negative">
                  {nameErrors[0]}
                </p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${uid}-desc`} className="text-sm font-medium text-fg">
                Description <span className="text-fg-subtle">(optional)</span>
              </label>
              <Textarea
                id={`${uid}-desc`}
                value={state.description}
                rows={2}
                placeholder="A note for yourself: the idea behind it, when it should work…"
                aria-invalid={descErrors.length > 0 || undefined}
                aria-describedby={descErrors.length ? `${uid}-desc-err` : undefined}
                onChange={(e) => patch({ description: e.target.value })}
                className="max-w-2xl"
              />
              {descErrors.length > 0 && (
                <p id={`${uid}-desc-err`} className="text-sm text-negative">
                  {descErrors[0]}
                </p>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${uid}-tf`} className="text-sm font-medium text-fg">
                How often to check
              </label>
              <Select value={state.timeframe} onValueChange={(tf) => patch({ timeframe: tf as Timeframe })}>
                <SelectTrigger id={`${uid}-tf`} className="w-full max-w-xs" aria-describedby={`${uid}-tf-hint`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {catalog.timeframes.map((tf) => (
                    <SelectItem key={tf} value={tf}>
                      {TIMEFRAME_WORDS[tf]?.[0] ?? tf} ({tf})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p id={`${uid}-tf-hint`} className="text-sm text-fg-muted">
                {timeframeText(state.timeframe)}. Rules only look at finished candles.
              </p>
            </div>
          </section>

          {/* ── WHEN ─────────────────────────────────────── */}
          <section aria-labelledby={`${uid}-when`} className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 id={`${uid}-when`} className="text-xl font-extrabold tracking-tight text-fg">
                  <span className="mr-2.5 inline-flex size-7 translate-y-[-2px] items-center justify-center rounded-full bg-primary align-middle text-sm font-extrabold text-primary-foreground">1<span className="sr-only"> ·</span></span>When
                </h2>
                <p className="text-sm text-fg-muted">The conditions that must be true on a finished candle. Use a buy rule, a sell rule, or both.</p>
              </div>
              <p className={cn("num text-sm", canAdd ? "text-fg-muted" : "text-warning")} aria-live="polite">
                {total} of {max} conditions used
              </p>
            </div>
            {problemsFor("entry").length > 0 && <p className="text-sm text-negative">{problemsFor("entry")[0]}</p>}
            {problemsFor("total").length > 0 && <p className="text-sm text-negative">{problemsFor("total")[0]}</p>}
            <GroupCard
              catalog={catalog}
              title="Buy (go up) when…"
              hint="A match proposes a BUY: Rise on Rise/Fall, Up on Multipliers, a long position on Spot."
              switchLabel="Use a buy rule"
              group={state.buy}
              onToggle={(on) => toggle("buy", on)}
              onChange={(buy) => patch({ buy })}
              canAdd={canAdd}
              problemsFor={problemsFor}
              groupProblems={problemsFor("buy")}
            />
            <GroupCard
              catalog={catalog}
              title="Sell (go down) when…"
              hint="A match proposes a SELL: Fall on Rise/Fall, Down on Multipliers, a short position on Spot."
              switchLabel="Use a sell rule"
              group={state.sell}
              onToggle={(on) => toggle("sell", on)}
              onChange={(sell) => patch({ sell })}
              canAdd={canAdd}
              problemsFor={problemsFor}
              groupProblems={problemsFor("sell")}
              newCondition={() => mirrorCondition(defaultCondition(catalog))}
            />
            <Accordion type="single" collapsible defaultValue={state.filters.length > 0 ? "filters" : undefined} className="rounded-xl border border-line bg-card px-4">
              <AccordionItem value="filters">
                <AccordionTrigger className="py-3">
                  <span className="flex flex-col items-start">
                    <span className="font-semibold text-fg">Only trade when… (optional)</span>
                    <span className="text-sm font-normal text-fg-muted">
                      {state.filters.length ? `${state.filters.length} filter${state.filters.length > 1 ? "s" : ""} — all must hold` : "Filters that must all hold before any buy or sell, e.g. a trend filter."}
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent className="pb-4">
                  <ConditionList
                    catalog={catalog}
                    conditions={state.filters}
                    onChange={(filters) => patch({ filters })}
                    canAdd={canAdd}
                    problemsFor={problemsFor}
                    addLabel="Add a filter"
                    newCondition={filterCondition}
                  />
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </section>

          {/* ── THEN ─────────────────────────────────────── */}
          <section aria-labelledby={`${uid}-then`} className="flex flex-col gap-3">
            <h2 id={`${uid}-then`} className="text-xl font-extrabold tracking-tight text-fg">
              <span className="mr-2.5 inline-flex size-7 translate-y-[-2px] items-center justify-center rounded-full bg-primary align-middle text-sm font-extrabold text-primary-foreground">2<span className="sr-only"> ·</span></span>Then
            </h2>
            <ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">
              <li>A Buy match proposes a BUY; a Sell match proposes a SELL — with the stop and target below.</li>
              <li>Your risk limits still decide: the STOP switch, mode, risk profile, daily loss limits, stake limits and sessions all apply, and they set the size.</li>
              <li>If buy and sell match on the same candle, nothing is traded.</li>
            </ul>
          </section>

          {/* ── EXIT ─────────────────────────────────────── */}
          <section aria-labelledby={`${uid}-exit`} className="flex flex-col gap-4">
            <div>
              <h2 id={`${uid}-exit`} className="text-xl font-extrabold tracking-tight text-fg">
                <span className="mr-2.5 inline-flex size-7 translate-y-[-2px] items-center justify-center rounded-full bg-primary align-middle text-sm font-extrabold text-primary-foreground">3<span className="sr-only"> ·</span></span>Exit
              </h2>
              <p className="text-sm text-fg-muted">How a trade ends depends on the contract you choose when you activate the strategy.</p>
            </div>
            <ContractExitNotes catalog={catalog} />
            <StopTargetEditor
              catalog={catalog}
              stop={state.stop}
              target={state.target}
              onStop={(stop) => patch({ stop })}
              onTarget={(target) => patch({ target })}
              stopProblems={problemsFor("stop")}
              targetProblems={problemsFor("target")}
            />
            {(hasBuy || state.closeBuy) && (
              <GroupCard
                catalog={catalog}
                title="Close a buy early when… (optional)"
                hint="Spot and Multiplier only — Rise/Fall always runs to expiry."
                switchLabel="Use an early exit for buys"
                group={state.closeBuy}
                onToggle={(on) => toggle("closeBuy", on)}
                onChange={(closeBuy) => patch({ closeBuy })}
                canAdd={canAdd}
                problemsFor={problemsFor}
                groupProblems={problemsFor("closeBuy")}
              />
            )}
            {(hasSell || state.closeSell) && (
              <GroupCard
                catalog={catalog}
                title="Close a sell early when… (optional)"
                hint="Spot and Multiplier only — Rise/Fall always runs to expiry."
                switchLabel="Use an early exit for sells"
                group={state.closeSell}
                onToggle={(on) => toggle("closeSell", on)}
                onChange={(closeSell) => patch({ closeSell })}
                canAdd={canAdd}
                problemsFor={problemsFor}
                groupProblems={problemsFor("closeSell")}
              />
            )}
          </section>

          {strategy && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${uid}-notes`} className="text-sm font-medium text-fg">
                What changed? <span className="text-fg-subtle">(optional, saved with the new version)</span>
              </label>
              <Input id={`${uid}-notes`} value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} className="max-w-lg" placeholder="e.g. Slower EMAs" />
            </div>
          )}
        </form>

        {/* ── Preview + save ───────────────────────────── */}
        <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:self-start lg:overflow-y-auto" aria-label="Preview and save">
          <div className="rounded-lg bg-card p-5 shadow-card ring-1 ring-line">
            <h2 className="eyebrow text-brand-ink">In plain English</h2>
            <div aria-live="polite" className="mt-2 space-y-1.5 text-sm leading-relaxed text-fg">
              {lines.map((l) => (
                <p key={l}>{l}</p>
              ))}
            </div>
          </div>

          <div ref={summaryRef} tabIndex={-1} className="flex flex-col gap-3 outline-none">
            {apiProblems.length > 0 && (
              <Notice tone="danger" title="The rules need a fix:">
                <ul className="list-disc space-y-0.5 pl-4">
                  {apiProblems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </Notice>
            )}
            {apiError && <Notice tone="danger" title="Couldn't save">{apiError}</Notice>}
            {problems.length > 0 && (
              <div className={cn("rounded-lg border px-4 py-3 text-sm", attempted ? "border-negative/30 bg-negative-soft" : "border-line bg-surface-raised/50")} role={attempted ? "alert" : undefined}>
                <p className="font-medium text-fg">{attempted ? "Fix these before saving:" : "Still to do:"}</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-fg-muted">
                  {problems.map((p) => (
                    <li key={`${p.at}:${p.text}`}>{p.text}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Button type="button" size="lg" onClick={() => void save()} disabled={busy}>
              {busy ? <Loader2 aria-hidden className="animate-spin" /> : <Save aria-hidden />}
              {busy ? "Saving…" : strategy ? "Save as a new version" : "Save strategy"}
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link href="/strategies">
                <ArrowLeft aria-hidden /> Back to my strategies
              </Link>
            </Button>
            <p className="text-xs text-fg-subtle">
              Nothing is saved until you press Save. {strategy ? "Saving adds a new version; earlier versions, trades and backtests keep theirs." : "You can test it on past data and activate it after saving."}
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

function SavedPanel({ saved, onKeepEditing }: { saved: Saved; onKeepEditing: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headingRef.current?.focus(), []);
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center rounded-xl border border-line bg-card px-6 py-10 text-center">
      <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-positive-soft">
        <CircleCheck aria-hidden className="size-5 text-positive" />
      </div>
      <h2 ref={headingRef} tabIndex={-1} className="text-xl font-extrabold tracking-tight text-fg outline-none">
        {saved.isNew ? `“${saved.name}” is saved` : saved.version ? `Saved “${saved.name}” as version ${saved.version}` : `Saved “${saved.name}”`}
      </h2>
      <p className="mt-1.5 max-w-md text-sm text-fg-muted">Next: see how it would have done on past data, then run it on a demo account. Nothing trades until you activate it.</p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        <Button asChild>
          <Link href={`/strategies?test=${encodeURIComponent(saved.id)}`}>
            <FlaskConical aria-hidden /> Test it on history
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link href={`/strategies?activate=${encodeURIComponent(saved.id)}`}>
            <Power aria-hidden /> Activate it
          </Link>
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap justify-center gap-2">
        <Button asChild variant="ghost" size="sm">
          <Link href="/strategies">Back to my strategies</Link>
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onKeepEditing}>
          Keep editing
        </Button>
      </div>
    </div>
  );
}
