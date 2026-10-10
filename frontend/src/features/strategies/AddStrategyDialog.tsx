"use client";

import { ArrowLeft, FileJson, LayoutTemplate, Loader2, MessageSquareText, SlidersHorizontal, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";
import { Notice } from "@/components/app/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { FAMILY_LABEL } from "@/lib/contracts";
import { useApi } from "@/lib/hooks";
import type { ContractFamily, RulesCatalog, Strategy, StrategyDraft, Timeframe } from "@/lib/types";
import { cn } from "@/lib/utils";
import { storeDraft } from "./builder/draft";
import { ruleLines } from "./builder/preview";

type Step = "choose" | "describe" | "result" | "import";

export const DESCRIPTION_MIN = 10;
export const DESCRIPTION_LIMIT = 2000;
export const IMPORT_MAX_BYTES = 131_072;
const ANY = "any";
const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"];
const FAMILIES: ContractFamily[] = ["RISE_FALL", "MULTIPLIER", "SPOT"];

export const AI_NOT_CONFIGURED = "Plain-English drafting isn't set up on this server (the administrator needs to add an Anthropic API key).";

/** Plain-English message for a failed draft request. */
export function draftErrorMessage(e: unknown): string {
  if (!(e instanceof ApiError)) return "Something went wrong. Please try again.";
  switch (e.code) {
    case "ai_not_configured":
      return AI_NOT_CONFIGURED;
    case "ai_refused":
      return "Claude declined to draft this. Describe a rule-based idea using prices and indicators (for example moving averages, RSI, breakouts).";
    case "ai_incomplete":
      return "The draft was cut off before it was finished. Try a shorter, simpler description.";
    case "ai_invalid_draft":
      return "Claude couldn't turn this into rules the platform accepts. Try simpler wording, or build it step by step.";
    case "ai_rate_limited":
      return "The drafting service is busy right now. Please try again in a minute.";
    case "ai_unavailable":
      return "The drafting service couldn't be reached. Please try again in a little while.";
  }
  if (e.status === 429) return "You've reached the drafting limit for now (a few drafts per hour). Try again later, or build it step by step.";
  if (e.status === 0) return e.message;
  return e.message || "Drafting failed. Please try again.";
}

/** Parse a strategy file's text. Returns the object, or a friendly error. */
export function parseStrategyFile(text: string): { ok: true; data: Record<string, unknown> } | { ok: false; error: string } {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { ok: false, error: "This file isn't valid JSON. Choose a strategy file exported from 2kPilot (…tradepilot.json)." };
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return { ok: false, error: "This file doesn't contain a strategy." };
  const obj = data as Record<string, unknown>;
  if (obj.format !== "tradepilot.strategy") return { ok: false, error: "This is not a 2kPilot strategy file." };
  if (!obj.rules || typeof obj.rules !== "object") return { ok: false, error: "This strategy file has no rules." };
  return { ok: true, data: obj };
}

const CHOICE_ART: Record<string, string> = {
  template: "linear-gradient(160deg, #9e4fe0, #5a1389)",
  build: "linear-gradient(160deg, #6c25b0, #2b0b4a)",
  describe: "linear-gradient(160deg, #303033, #0e0e10)",
};

function Choice({ icon: Icon, title, children, onClick, disabled, badge, art }: { icon: typeof LayoutTemplate; title: string; children: ReactNode; onClick: () => void; disabled?: boolean; badge?: string; art: keyof typeof CHOICE_ART }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "group flex w-full items-start gap-4 rounded-lg bg-surface-raised p-3 text-left ring-1 ring-line transition-[background-color,box-shadow,transform] outline-none sm:flex-col sm:gap-0 sm:p-3",
        "hover:bg-surface-hover hover:ring-line-strong focus-visible:ring-3 focus-visible:ring-ring/50 enabled:active:scale-[0.99]",
        "disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-surface-raised",
      )}
    >
      <span aria-hidden className="relative flex size-16 shrink-0 items-center justify-center overflow-hidden rounded-md shadow-raised sm:aspect-[4/3] sm:size-auto sm:w-full" style={{ background: CHOICE_ART[art] }}>
        <span className="absolute inset-0 bg-[radial-gradient(100%_80%_at_20%_0%,rgb(255_255_255/0.3),transparent_60%)]" />
        <Icon className="relative size-7 text-white transition-transform duration-300 group-enabled:group-hover:scale-110 sm:size-10" strokeWidth={1.75} />
      </span>
      <span className="min-w-0 sm:mt-3.5 sm:px-1 sm:pb-1">
        <span className="flex flex-wrap items-center gap-2 font-bold text-fg">
          {title}
        </span>
        {badge && <span className="mt-1.5 inline-block rounded-full bg-[color-mix(in_oklab,var(--primary)_14%,transparent)] px-2 py-0.5 text-[11px] font-bold text-brand-ink">{badge}</span>}
        <span className="mt-1.5 block text-[13px] leading-relaxed text-fg-muted">{children}</span>
      </span>
    </button>
  );
}

/**
 * "Add a strategy": start from a template, build step by step, describe it in
 * plain English (drafted by Claude, reviewed in the builder), or import a file.
 * Nothing is saved without the user pressing Save (import saves on confirm).
 */
export function AddStrategyDialog({
  open,
  onOpenChange,
  catalog: catalogProp,
  onImported,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog?: RulesCatalog | null;
  /** Called after a successful import (e.g. to reload the list). */
  onImported?: (strategy: Strategy) => void;
}) {
  const router = useRouter();
  const [step, setStep] = useState<Step>("choose");
  const fetched = useApi<RulesCatalog>(open && !catalogProp ? "/strategies/catalog" : null);
  const catalog = catalogProp ?? fetched.data;
  const aiOff = catalog?.ai_drafting_available === false;

  const close = (next: boolean) => {
    onOpenChange(next);
    if (!next) setStep("choose");
  };

  const go = (href: string) => {
    close(false);
    router.push(href);
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className={cn("max-h-[calc(100dvh-2rem)] overflow-y-auto", step === "choose" ? "sm:max-w-3xl" : "sm:max-w-xl")}>
        {step === "choose" && (
          <>
            <DialogHeader>
              <DialogTitle className="text-2xl font-extrabold">Add a strategy</DialogTitle>
              <DialogDescription>Three ways to make one — none needs programming. You can test it on past data before it ever trades.</DialogDescription>
            </DialogHeader>
            <div className="grid gap-3 sm:grid-cols-3">
              <Choice art="template" icon={LayoutTemplate} title="Start from a template" badge="Recommended for beginners" onClick={() => go("/strategies?tab=templates")}>
                Six ready-made rule sets with plain explanations. Use one as it is, or copy it and change it.
              </Choice>
              <Choice art="build" icon={SlidersHorizontal} title="Build it step by step" onClick={() => go("/strategies/new")}>
                Pick conditions from lists: when to buy, when to sell, and how trades end.
              </Choice>
              <Choice art="describe" icon={MessageSquareText} title="Describe it in your words" onClick={() => setStep("describe")} disabled={aiOff}>
                {aiOff ? AI_NOT_CONFIGURED : "Claude drafts the rules from your description; you review and edit them before saving."}
              </Choice>
            </div>
            <div className="border-t border-line pt-3">
              <Button type="button" variant="ghost" size="sm" onClick={() => setStep("import")}>
                <FileJson aria-hidden /> Import a strategy file (.json)
              </Button>
            </div>
          </>
        )}
        {step === "describe" || step === "result" ? (
          <DescribeStep catalog={catalog ?? null} step={step} setStep={setStep} onBack={() => setStep("choose")} onReview={() => go("/strategies/new?from=draft")} />
        ) : null}
        {step === "import" && (
          <ImportStep
            onBack={() => setStep("choose")}
            onDone={(s) => {
              toast.success(`Imported “${s.name}”`);
              onImported?.(s);
              go("/strategies");
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

// ── C: describe it ──────────────────────────────────────────────────────

function DescribeStep({
  catalog,
  step,
  setStep,
  onBack,
  onReview,
}: {
  catalog: RulesCatalog | null;
  step: "describe" | "result";
  setStep: (s: Step) => void;
  onBack: () => void;
  onReview: () => void;
}) {
  const uid = useId();
  const [description, setDescription] = useState("");
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState<string>(ANY);
  const [family, setFamily] = useState<string>(ANY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [draft, setDraft] = useState<StrategyDraft | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const length = description.trim().length;
  const tooShort = length < DESCRIPTION_MIN;
  const tooLong = description.length > DESCRIPTION_LIMIT;

  const submit = async () => {
    if (tooShort || tooLong || busy) return;
    setBusy(true);
    setError(null);
    setProblems([]);
    setFieldErrors({});
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    try {
      const body: Record<string, string> = { description: description.trim() };
      if (symbol.trim()) body.symbol = symbol.trim();
      if (timeframe !== ANY) body.timeframe = timeframe;
      if (family !== ANY) body.contract_family = family;
      const result = await api<StrategyDraft>("/strategies/draft", { method: "POST", body, signal: controller.signal });
      setDraft(result);
      setStep("result");
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length > 0 && !e.code.startsWith("ai_")) {
        setFieldErrors(e.fieldErrors);
      } else {
        setError(draftErrorMessage(e));
        if (e instanceof ApiError) setProblems(e.problems);
      }
    } finally {
      if (abort.current === controller) setBusy(false);
    }
  };

  const review = () => {
    if (!draft?.rules) return;
    const ok = storeDraft({
      rules: draft.rules,
      description: description.trim().slice(0, DESCRIPTION_LIMIT),
      explanation: draft.explanation,
      warnings: draft.warnings ?? [],
      unsupported: draft.unsupported ?? [],
      source: "ai",
    });
    if (!ok) {
      setError("Your browser blocked temporary storage, so the draft can't be opened in the builder. Allow site data for this page and try again.");
      return;
    }
    onReview();
  };

  if (step === "result" && draft) {
    const lines = draft.rules && catalog ? ruleLines(draft.rules, catalog) : draft.rules_text ? [draft.rules_text] : [];
    return (
      <>
        <DialogHeader>
          <DialogTitle>{draft.rules ? "Here's the draft" : "No rules could be drafted"}</DialogTitle>
          <DialogDescription>{draft.rules ? "Read it carefully. You'll review and can change every rule in the builder before saving." : "Here's why. You can change your description and try again."}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          {draft.explanation && <p className="text-sm whitespace-pre-line text-fg">{draft.explanation}</p>}
          {lines.length > 0 && (
            <div className="rounded-lg border border-line bg-surface-raised/50 p-3">
              <p className="text-xs font-medium tracking-wide text-fg-subtle uppercase">The rules in plain English</p>
              <div className="mt-1.5 space-y-1 text-sm text-fg">
                {lines.map((l) => (
                  <p key={l}>{l}</p>
                ))}
              </div>
            </div>
          )}
          {draft.warnings.length > 0 && (
            <Notice tone="warning" title="Things to check">
              <ul className="list-disc space-y-0.5 pl-4">
                {draft.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Notice>
          )}
          {draft.unsupported.length > 0 && (
            <Notice tone="warning" title="Not possible here:">
              <ul className="list-disc space-y-0.5 pl-4">
                {draft.unsupported.map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
            </Notice>
          )}
          {error && <Notice tone="danger">{error}</Notice>}
        </div>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
          <Button type="button" variant="ghost" onClick={() => setStep("describe")}>
            <ArrowLeft aria-hidden /> Change the description
          </Button>
          {draft.rules && (
            <Button type="button" onClick={review}>
              Review and edit in the builder
            </Button>
          )}
        </div>
      </>
    );
  }

  const descErr = fieldErrors.description?.[0];
  return (
    <>
      <DialogHeader>
        <DialogTitle>Describe it in your words</DialogTitle>
        <DialogDescription>Say when to buy, when to sell, and how trades should end. Claude turns it into rules you can check and change.</DialogDescription>
      </DialogHeader>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${uid}-desc`} className="text-sm font-medium text-fg">
            Your strategy idea
          </label>
          <Textarea
            id={`${uid}-desc`}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={5}
            disabled={busy}
            placeholder="e.g. Buy when the 20 EMA crosses above the 50 EMA and RSI is below 70. Sell on the opposite cross. Stop at 2 ATR, target twice the stop."
            aria-invalid={tooLong || Boolean(descErr) || undefined}
            aria-describedby={`${uid}-desc-count${descErr ? ` ${uid}-desc-err` : ""}`}
          />
          <div className="flex flex-wrap justify-between gap-2 text-xs">
            <span id={`${uid}-desc-count`} className={cn("num", tooLong ? "text-negative" : "text-fg-subtle")}>
              {description.length} / {DESCRIPTION_LIMIT} characters{tooShort && description.length > 0 ? ` (at least ${DESCRIPTION_MIN})` : ""}
            </span>
          </div>
          {descErr && (
            <p id={`${uid}-desc-err`} className="text-sm text-negative">
              {descErr}
            </p>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${uid}-symbol`} className="text-sm font-medium text-fg">
              Symbol <span className="text-fg-subtle">(optional)</span>
            </label>
            <Input
              id={`${uid}-symbol`}
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              disabled={busy}
              maxLength={40}
              placeholder="e.g. R_100"
              aria-invalid={fieldErrors.symbol ? true : undefined}
              aria-describedby={fieldErrors.symbol ? `${uid}-symbol-err` : undefined}
            />
            {fieldErrors.symbol && (
              <p id={`${uid}-symbol-err`} className="text-sm text-negative">
                {fieldErrors.symbol[0]}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${uid}-tf`} className="text-sm font-medium text-fg">
              Timeframe <span className="text-fg-subtle">(optional)</span>
            </label>
            <Select value={timeframe} onValueChange={setTimeframe} disabled={busy}>
              <SelectTrigger id={`${uid}-tf`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Let Claude choose</SelectItem>
                {(catalog?.timeframes ?? TIMEFRAMES).map((tf) => (
                  <SelectItem key={tf} value={tf}>
                    {tf}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${uid}-family`} className="text-sm font-medium text-fg">
              Contract <span className="text-fg-subtle">(optional)</span>
            </label>
            <Select value={family} onValueChange={setFamily} disabled={busy}>
              <SelectTrigger id={`${uid}-family`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Not sure yet</SelectItem>
                {FAMILIES.map((f) => (
                  <SelectItem key={f} value={f}>
                    {FAMILY_LABEL[f]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <p className="text-xs text-fg-subtle">Your description is sent to Anthropic to draft the rules; don&apos;t include personal information. Nothing is saved until you review the draft and press Save.</p>
        {error && (
          <Notice tone="danger">
            {error}
            {problems.length > 0 && (
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
          </Notice>
        )}
        {busy && (
          <p role="status" className="flex items-center gap-2 text-sm text-fg-muted">
            <Loader2 aria-hidden className="size-4 animate-spin" /> Drafting… this can take up to a minute.
          </p>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
          <Button type="button" variant="ghost" onClick={onBack} disabled={busy}>
            <ArrowLeft aria-hidden /> Back
          </Button>
          <Button type="submit" disabled={busy || tooShort || tooLong}>
            {busy ? <Loader2 aria-hidden className="animate-spin" /> : <MessageSquareText aria-hidden />} {busy ? "Drafting…" : "Draft the rules"}
          </Button>
        </div>
      </form>
    </>
  );
}

// ── Import ──────────────────────────────────────────────────────────────

function ImportStep({ onBack, onDone }: { onBack: () => void; onDone: (s: Strategy) => void }) {
  const uid = useId();
  const [file, setFile] = useState<Record<string, unknown> | null>(null);
  const [fileName, setFileName] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  const pick = async (f: File | undefined) => {
    setError(null);
    setNameError(null);
    setProblems([]);
    setFile(null);
    if (!f) return;
    setFileName(f.name);
    if (f.size > IMPORT_MAX_BYTES) {
      setError("The file is too large (128 KB at most).");
      return;
    }
    const parsed = parseStrategyFile(await f.text());
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setFile(parsed.data);
    setName(typeof parsed.data.name === "string" ? parsed.data.name : f.name.replace(/(\.tradepilot)?\.json$/i, ""));
  };

  const submit = async () => {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    setNameError(null);
    setProblems([]);
    try {
      const created = await api<Strategy>("/strategies/import", { method: "POST", body: { ...file, name: name.trim() } });
      onDone(created);
    } catch (e) {
      if (e instanceof ApiError) {
        setProblems(e.problems);
        setNameError(e.field("name"));
        const other = Object.entries(e.fieldErrors)
          .filter(([k]) => k !== "name")
          .map(([, v]) => v[0]);
        if (other.length) setError(other.join(" "));
        else if (!e.field("name") && e.problems.length === 0) setError(e.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Import a strategy file</DialogTitle>
        <DialogDescription>A .json file exported from 2kPilot (Export on a strategy card). Its rules are checked before anything is saved.</DialogDescription>
      </DialogHeader>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${uid}-file`} className="text-sm font-medium text-fg">
            Strategy file
          </label>
          <Input
            id={`${uid}-file`}
            type="file"
            accept=".json,application/json"
            disabled={busy}
            onChange={(e) => void pick(e.target.files?.[0])}
            className="h-auto py-1.5"
          />
          <span className="text-xs text-fg-subtle">128 KB at most.</span>
        </div>
        {file && (
          <>
            {typeof file.description === "string" && file.description && <p className="text-sm text-fg-muted">{file.description}</p>}
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${uid}-name`} className="text-sm font-medium text-fg">
                Name
              </label>
              <Input
                id={`${uid}-name`}
                value={name}
                maxLength={120}
                onChange={(e) => setName(e.target.value)}
                aria-invalid={nameError ? true : undefined}
                aria-describedby={nameError ? `${uid}-name-err` : undefined}
              />
              {nameError && (
                <p id={`${uid}-name-err`} className="text-sm text-negative">
                  {nameError}
                </p>
              )}
            </div>
          </>
        )}
        {problems.length > 0 && (
          <Notice tone="danger" title="The rules need a fix:">
            <ul className="list-disc space-y-0.5 pl-4">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </Notice>
        )}
        {error && (
          <Notice tone="danger" title={fileName ? `Couldn't import ${fileName}` : "Couldn't import"}>
            {error}
          </Notice>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
          <Button type="button" variant="ghost" onClick={onBack} disabled={busy}>
            <ArrowLeft aria-hidden /> Back
          </Button>
          <Button type="submit" disabled={!file || busy || name.trim() === ""}>
            {busy ? <Loader2 aria-hidden className="animate-spin" /> : <Upload aria-hidden />} Import
          </Button>
        </div>
      </form>
    </>
  );
}
