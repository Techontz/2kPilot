"use client";

import { ArrowLeft, Copy, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useId, useState } from "react";
import { toast } from "sonner";
import { ErrorState, ListSkeleton, Notice } from "@/components/app/states";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { RuleSet, RulesCatalog, Strategy, StrategyVersion } from "@/lib/types";
import { type StoredDraft, readDraft } from "./draft";
import { defaultState, rulesToState } from "./model";
import { StrategyBuilder } from "./StrategyBuilder";

function PageHeader({ title, subtitle }: { title: string; subtitle?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-2 pt-2 sm:pt-4">
      <Link href="/strategies" className="inline-flex h-9 w-fit items-center gap-1.5 rounded-full bg-surface-hover pr-4 pl-3 text-sm font-bold text-fg-muted transition-colors hover:text-fg">
        <ArrowLeft aria-hidden className="size-4" /> Strategies
      </Link>
      <h1 className="title-xl mt-3 text-4xl text-fg sm:text-5xl">{title}</h1>
      {subtitle && <div className="max-w-2xl text-sm text-fg-muted">{subtitle}</div>}
    </div>
  );
}

function useCatalog() {
  return useApi<RulesCatalog>("/strategies/catalog");
}

// ── New strategy ────────────────────────────────────────────────────────

/** /strategies/new — an empty builder, or a reviewed plain-English draft (?from=draft). */
export function NewStrategyScreen() {
  const params = useSearchParams();
  const fromDraft = params.get("from") === "draft";
  const catalog = useCatalog();
  return (
    <>
      <PageHeader
        title="New strategy"
        subtitle="Pick conditions from the lists — no programming. The plain-English preview shows exactly what the robot will check."
      />
      {catalog.error ? (
        <ErrorState message={catalog.error} onRetry={() => void catalog.reload()} />
      ) : !catalog.data ? (
        <ListSkeleton rows={5} />
      ) : (
        <NewStrategyBuilder catalog={catalog.data} fromDraft={fromDraft} />
      )}
    </>
  );
}

/** Mounted on the client only after the catalogue loads, so reading sessionStorage here is safe. */
function NewStrategyBuilder({ catalog, fromDraft }: { catalog: RulesCatalog; fromDraft: boolean }) {
  const [draft] = useState<StoredDraft | null>(() => (fromDraft ? readDraft() : null));
  const [initial] = useState(() => (draft ? rulesToState(draft.rules, catalog, { name: draft.name, description: draft.description }) : defaultState(catalog)));
  const banner = fromDraft ? (
    draft ? (
      <DraftReview draft={draft} />
    ) : (
      <Notice tone="warning" title="The draft isn't here any more">
        Drafts only live in the browser tab that made them. Describe your idea again from <strong>Add a strategy</strong>, or build it step by step below.
      </Notice>
    )
  ) : undefined;
  return <StrategyBuilder catalog={catalog} initial={initial} source={draft ? "ai" : "builder"} banner={banner} />;
}

export function DraftReview({ draft }: { draft: Pick<StoredDraft, "explanation" | "warnings" | "unsupported"> }) {
  return (
    <div className="flex flex-col gap-3">
      <Notice tone="info" title="Drafted from your description — review every rule before saving">
        {draft.explanation && <p className="whitespace-pre-line">{draft.explanation}</p>}
        <p className="mt-1">AI drafts can misunderstand. Check the plain-English preview matches what you meant. Nothing is saved until you press Save.</p>
      </Notice>
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
    </div>
  );
}

// ── Edit strategy ───────────────────────────────────────────────────────

export function latestVersion(strategy: Strategy): StrategyVersion | null {
  if (strategy.latest_version) return strategy.latest_version;
  return [...(strategy.versions ?? [])].sort((a, b) => b.version - a.version)[0] ?? null;
}

/** /strategies/[id]/edit — edit a rule-based strategy you own (a save adds a version). */
export function EditStrategyScreen({ id }: { id: string }) {
  const catalog = useCatalog();
  const strategies = useApi<Strategy[]>("/strategies");
  const { isAdmin } = useSession();

  const error = catalog.error ?? strategies.error;
  if (error) {
    return (
      <>
        <PageHeader title="Edit strategy" />
        <ErrorState
          message={error}
          onRetry={() => {
            void catalog.reload();
            void strategies.reload();
          }}
        />
      </>
    );
  }
  if (!catalog.data || !strategies.data) {
    return (
      <>
        <PageHeader title="Edit strategy" />
        <ListSkeleton rows={5} />
      </>
    );
  }

  const strategy = strategies.data.find((s) => s.id === id);
  if (!strategy) {
    return (
      <>
        <PageHeader title="Edit strategy" />
        <Notice tone="warning" title="Strategy not found">
          It may have been deleted, or it belongs to someone else. <Link href="/strategies" className="underline underline-offset-4">Back to my strategies</Link>
        </Notice>
      </>
    );
  }

  const origin = strategy.copied_from_id ? strategies.data.find((s) => s.id === strategy.copied_from_id) : undefined;
  const subtitle = (
    <>
      <span className="font-medium text-fg">{strategy.name}</span>
      {origin?.built_in && <span> · Your copy of {origin.name}</span>}
    </>
  );

  if (strategy.key !== "rules") {
    return (
      <>
        <PageHeader title="Edit strategy" subtitle={subtitle} />
        <Notice tone="info" title="This strategy can&apos;t be edited in the builder">
          {strategy.name} is an advanced, code-based strategy. Its settings are numbers you can change from the strategy card on the Strategies page, not rules built from conditions.
        </Notice>
      </>
    );
  }

  const version = latestVersion(strategy);
  if (!version) {
    return (
      <>
        <PageHeader title="Edit strategy" subtitle={subtitle} />
        <ErrorState message="This strategy has no saved rules yet." />
      </>
    );
  }

  if (strategy.archived) {
    return (
      <>
        <PageHeader title="Edit strategy" subtitle={subtitle} />
        <Notice tone="warning" title="This strategy is archived">
          Archived strategies keep their history but can&apos;t get new versions.
        </Notice>
      </>
    );
  }

  const canEdit = strategy.built_in ? isAdmin && strategy.editable !== false : strategy.editable !== false;
  if (!canEdit) {
    return (
      <>
        <PageHeader title="Edit strategy" subtitle={subtitle} />
        {strategy.built_in ? (
          <CopyTemplate strategy={strategy} intro="Templates are read-only — copy it first. Your copy is yours to change; the template stays as it is." />
        ) : (
          <Notice tone="warning" title="You can't edit this strategy">
            It isn&apos;t yours. <Link href="/strategies" className="underline underline-offset-4">Back to my strategies</Link>
          </Notice>
        )}
      </>
    );
  }

  const initial = rulesToState(version.parameters as unknown as RuleSet, catalog.data, { name: strategy.name, description: strategy.description });
  return (
    <>
      <PageHeader title="Edit strategy" subtitle={<>{subtitle} · version {version.version}</>} />
      <StrategyBuilder
        key={strategy.id}
        catalog={catalog.data}
        initial={initial}
        strategy={strategy}
        banner={
          strategy.built_in ? (
            <Notice tone="warning" title="You're editing a shared template">
              As an administrator, saving adds a version that every user sees. To experiment, make your own copy instead.
              <div className="mt-2">
                <CopyTemplate strategy={strategy} compact />
              </div>
            </Notice>
          ) : undefined
        }
      />
    </>
  );
}

/** "Copy it first": name the copy, then edit it. */
function CopyTemplate({ strategy, intro, compact }: { strategy: Pick<Strategy, "id" | "name">; intro?: string; compact?: boolean }) {
  const router = useRouter();
  const uid = useId();
  const [name, setName] = useState(`My ${strategy.name}`.slice(0, 120));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const copy = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api<{ id: string; name: string }>(`/strategies/${strategy.id}/copy`, { method: "POST", body: { name: name.trim() } });
      toast.success(`Copied as “${created.name}”`);
      router.push(`/strategies/${created.id}/edit`);
    } catch (e) {
      setError(e instanceof ApiError ? (e.field("name") ?? e.message) : "Something went wrong.");
      setBusy(false);
    }
  };

  const form = (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void copy();
      }}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label htmlFor={`${uid}-name`} className="text-sm font-medium text-fg">
          Name of your copy
        </label>
        <Input
          id={`${uid}-name`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${uid}-err` : undefined}
          className="min-w-48"
        />
      </div>
      <Button type="submit" disabled={busy || name.trim() === ""}>
        {busy ? <Loader2 aria-hidden className="animate-spin" /> : <Copy aria-hidden />} Copy and edit
      </Button>
      {error && (
        <p id={`${uid}-err`} className="w-full text-sm text-negative">
          {error}
        </p>
      )}
    </form>
  );
  if (compact) return form;
  return (
    <div className="max-w-xl rounded-xl border border-line bg-card p-5">
      <p className="font-semibold text-fg">{strategy.name} is a template</p>
      {intro && <p className="mt-1 mb-4 text-sm text-fg-muted">{intro}</p>}
      {form}
    </div>
  );
}
