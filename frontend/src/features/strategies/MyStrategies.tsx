"use client";

import { Download, FlaskConical, MoreHorizontal, Pencil, Play, SlidersHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { EnvBadge, Pill, SourceBadge } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { PnlText } from "@/components/app/money";
import { Artwork } from "@/components/app/artwork";
import { CardsSkeleton, EmptyState, ErrorState } from "@/components/app/states";
import { Term } from "@/components/app/term";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { api, ApiError } from "@/lib/api";
import { contractSummary } from "@/lib/contracts";
import { formatPct, formatRelative } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { Assignment, Strategy } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EvaluationsSheet } from "./EvaluationsSheet";
import { exportStrategy } from "./exportStrategy";
import type { StrategyActions } from "./StrategiesSection";
import { StrategyInsights } from "./StrategyInsights";
import { isMine, isRuleBased, rulesText } from "./strategyUtils";

interface Loaded {
  data: Strategy[] | null;
  error: string | null;
  reload: () => Promise<unknown>;
}

export function MyStrategies({ strategies, actions, onAdd }: { strategies: Loaded; actions: StrategyActions; onAdd: () => void }) {
  if (!strategies.data) return strategies.error ? <ErrorState message={strategies.error} onRetry={() => void strategies.reload()} /> : <CardsSkeleton count={2} />;
  const list = strategies.data.filter(isMine);
  if (list.length === 0) {
    return (
      <Card>
        <EmptyState icon={SlidersHorizontal} title="You don't have a strategy yet"
          action={<><Button asChild><Link href="/strategies?tab=templates">Browse templates</Link></Button><Button variant="outline" onClick={onAdd}>Other ways to add one</Button></>}>
          The easiest start is a ready-made template: copy it, test it on past prices, then activate it on your demo account.
        </EmptyState>
      </Card>
    );
  }
  const templates = strategies.data.filter((s) => s.built_in && !isMine(s)).slice(0, 4);
  return (
    <div className="space-y-10">
      <section aria-labelledby="mine-title">
        <ShelfHeader id="mine-title" title="Your strategies" meta={`${list.length} ${list.length === 1 ? "strategy" : "strategies"}`} />
        <div className="grid items-start gap-4 xl:grid-cols-2">
          {list.map((s) => <StrategyCard key={s.id} strategy={s} actions={actions} />)}
        </div>
      </section>
      {templates.length > 0 && (
        <section aria-labelledby="try-title">
          <ShelfHeader id="try-title" title="Start from a template" href="/strategies?tab=templates" />
          <ul className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-4">
            {templates.map((t) => (
              <li key={t.id}>
                <Link href="/strategies?tab=templates" className="group block h-full rounded-lg bg-card p-3 ring-1 ring-line transition-colors hover:bg-surface-hover">
                  <Artwork seed={`${t.name} ${t.description}`} className="aspect-[16/9] w-full shadow-raised transition-transform duration-300 group-hover:scale-[1.02]" />
                  <p className="mt-3 truncate text-sm font-bold text-fg">{t.name}</p>
                  <p className="mt-0.5 line-clamp-2 text-xs text-fg-muted">{t.description}</p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/** Shelf title with an optional "Show all" link. */
export function ShelfHeader({ id, title, meta, href }: { id: string; title: string; meta?: string; href?: string }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-3">
      <h2 id={id} className="text-xl font-extrabold tracking-tight text-fg sm:text-2xl">
        {title}{meta && <span className="ml-2 text-sm font-semibold text-fg-subtle">{meta}</span>}
      </h2>
      {href && <Link href={href} className="shrink-0 text-sm font-bold text-fg-muted underline-offset-4 hover:text-fg hover:underline">Show all</Link>}
    </div>
  );
}

function StrategyCard({ strategy: s, actions }: { strategy: Strategy; actions: StrategyActions }) {
  const { isAdmin } = useSession();
  const { accounts } = useAppData();
  const [expanded, setExpanded] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [explain, setExplain] = useState<Assignment | null>(null);
  const action = useAction();
  const active = s.assignments.filter((a) => a.status === "ENABLED");
  const editable = isRuleBased(s) && (!s.built_in || isAdmin) && s.editable !== false;
  const currencies = new Set((accounts ?? []).map((a) => a.currency));
  const currency = currencies.size === 1 ? [...currencies][0] : undefined;
  const demo = s.performance?.demo;
  const bt = s.backtest;
  const text = rulesText(s);
  // One rule per line: sentences ("Buy when …. Sell when …. Stop: …") read far better than one dense paragraph on a phone.
  const rules = text.split(/(?<=\.)\s+(?=[A-Z])/).filter(Boolean);

  const deactivate = async (accountId: string) => {
    const ok = await action.run(() => api(`/strategies/${s.id}/deactivate`, { method: "POST", body: { account_id: accountId } }));
    if (ok) {
      toast.success(`${s.name} deactivated`, { description: "It no longer opens trades on that account. Open trades finish normally." });
      actions.reload();
    }
  };
  const remove = async () => {
    const res = await action.run(() => api<{ outcome: string }>(`/strategies/${s.id}`, { method: "DELETE" }));
    if (res) {
      setConfirmDelete(false);
      toast.success(res.outcome === "archived" ? `${s.name} archived` : `${s.name} deleted`, { description: res.outcome === "archived" ? "Its trades and tests stay in your history." : undefined });
      actions.reload();
    }
  };
  const download = async () => {
    try {
      await exportStrategy(s);
      toast.success("Strategy file downloaded");
    } catch (e) {
      toast.error("Export failed", { description: e instanceof ApiError || e instanceof Error ? e.message : undefined });
    }
  };

  return (
    <Card className="group/strategy transition-colors hover:bg-[color-mix(in_oklab,var(--card),var(--foreground)_2%)]">
      <CardHeader className="grid-cols-[auto_1fr_auto] gap-x-3.5 has-data-[slot=card-action]:grid-cols-[auto_1fr_auto] sm:gap-x-4">
        <div className="relative row-span-2 self-start">
          <Artwork seed={`${s.name} ${s.description}`} className="size-14 shadow-raised sm:size-24" />
          <button type="button" tabIndex={-1} aria-hidden onClick={() => actions.activate(s)}
            className="absolute right-1.5 bottom-1.5 flex size-10 translate-y-2 items-center justify-center rounded-full bg-primary text-primary-foreground opacity-0 shadow-fab transition-all duration-200 group-hover/strategy:translate-y-0 group-hover/strategy:opacity-100 hover:scale-105">
            <Play className="size-4 translate-x-px fill-current" />
          </button>
        </div>
        <div className="min-w-0">
          <CardTitle className="text-lg leading-tight font-extrabold break-words sm:text-xl">{s.name}</CardTitle>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <SourceBadge source={s.source} />
            {active.length > 0 ? <Pill tone="positive" dot>Active on {active.length}</Pill> : <Pill>Not active</Pill>}
            {s.entries_disabled && <Pill tone="negative" dot>Stopped by admin</Pill>}
          </div>
          {s.description && s.description !== text && <CardDescription className="mt-2 hidden sm:block">{s.description}</CardDescription>}
        </div>
        <CardAction className="col-start-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={`More actions for ${s.name}`}><MoreHorizontal aria-hidden /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {editable && <DropdownMenuItem asChild><Link href={`/strategies/${s.id}/edit`}><Pencil aria-hidden /> Edit rules</Link></DropdownMenuItem>}
              {isRuleBased(s) && <DropdownMenuItem onSelect={() => void download()}><Download aria-hidden /> Export (.json)</DropdownMenuItem>}
              {!s.built_in && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" onSelect={() => { action.reset(); setConfirmDelete(true); }}><Trash2 aria-hidden /> Delete</DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Phones: the description uses the full card width instead of the column beside the artwork. */}
        {s.description && s.description !== text && <p className="-mt-1 text-[15px] leading-relaxed text-fg-muted sm:hidden">{s.description}</p>}
        <div>
          <ul className="space-y-1.5 text-[15px] leading-relaxed text-fg sm:text-sm">
            {(expanded ? rules : rules.slice(0, 2)).map((r, i) => (
              <li key={i} className="flex gap-2.5">
                <span aria-hidden className="mt-[0.6em] size-1 shrink-0 rounded-full bg-fg-subtle" />
                <span className={cn("min-w-0 break-words", !expanded && "line-clamp-2")}>{r}</span>
              </li>
            ))}
          </ul>
          {(rules.length > 2 || text.length > 180) && <button type="button" className="touch-hit mt-1 text-xs font-semibold text-brand-ink hover:underline max-sm:mt-2 max-sm:text-sm" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{expanded ? "Show less" : "Show all rules"}</button>}
        </div>
        {!isRuleBased(s) && <StrategyInsights strategy={s} onChanged={actions.reload} />}
        <dl className="grid gap-2.5 sm:grid-cols-2 sm:gap-3">
          <div className="rounded-md bg-surface-raised p-3.5">
            <dt className="text-xs font-semibold text-fg-muted">Demo results (your Paper/demo trades)</dt>
            <dd className="mt-1 text-sm">
              {demo && demo.trades > 0 ? (
                <>
                  <PnlText value={demo.net_pnl} currency={currency} className="font-extrabold" /> · {demo.trades} trades · <Term id="winRate">{formatPct(demo.win_rate, 0)} wins</Term>
                  <span className="block text-xs text-fg-subtle">Last 30 days <PnlText value={demo.net_pnl_30d} currency={currency} /> · last trade {formatRelative(demo.last_trade_at)}</span>
                </>
              ) : <span className="text-fg-muted">Not traded on demo yet</span>}
            </dd>
          </div>
          <div className="rounded-md bg-surface-raised p-3.5">
            <dt className="text-xs font-semibold text-fg-muted">Latest test on history</dt>
            <dd className="mt-1 text-sm">
              {bt ? (
                <Link href={`/strategies/backtests/${bt.id}`} className="hover:underline">
                  <PnlText value={bt.net_pnl} currency="USD" className="font-extrabold" /> · {bt.trades ?? 0} trades · {formatPct(bt.win_rate, 0)} wins
                  <span className="block text-xs text-fg-subtle">{bt.symbol} {bt.timeframe} · max drawdown {formatPct(bt.max_drawdown_pct, 1)} · {formatRelative(bt.run_at)}</span>
                </Link>
              ) : <span className="text-fg-muted">Not tested yet</span>}
            </dd>
          </div>
        </dl>
        {s.assignments.length > 0 && (
          <ul className="space-y-2" aria-label="Where it runs">
            {s.assignments.map((a) => (
              <li key={a.id} className="flex flex-col gap-3 rounded-md px-3 py-3 ring-1 ring-line transition-colors hover:bg-surface-raised sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-2 sm:py-2.5">
                <span className="min-w-0 text-sm">
                  <span className="flex flex-wrap items-center gap-1.5">
                    {a.account && <EnvBadge env={a.account.environment} />}
                    <span className="font-bold text-fg">{a.symbol}</span>
                    <span className="text-fg-muted">on {a.account?.label ?? "account"}</span>
                    {a.status === "ENABLED" ? <Pill tone="positive" dot>Active</Pill> : <Pill>Paused</Pill>}
                  </span>
                  <span className="mt-1 block text-xs break-words text-fg-subtle sm:mt-0">{contractSummary(a.contract)}{a.last_bar_evaluated ? ` · checked ${formatRelative(a.last_bar_evaluated)}` : ""}</span>
                </span>
                <span className="flex gap-2 sm:gap-1 [&>*]:max-sm:flex-1">
                  <Button size="sm" variant="ghost" className="max-sm:bg-surface-hover" onClick={() => setExplain(a)}>Why no trade?</Button>
                  {a.status === "ENABLED" && a.account && <Button size="sm" variant="outline" disabled={action.busy} onClick={() => void deactivate(a.account!.id)}>Deactivate</Button>}
                </span>
              </li>
            ))}
          </ul>
        )}
        {action.error && !confirmDelete && <p role="alert" className="text-sm text-negative">{action.error}</p>}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2 border-t [&>*]:max-sm:flex-1">
        <Button onClick={() => actions.activate(s)} className="max-sm:basis-full"><Play aria-hidden /> {active.length ? "Activate on another market" : "Activate"}</Button>
        <Button variant="outline" onClick={() => actions.test(s)}><FlaskConical aria-hidden /> Test on history</Button>
        {editable && <Button variant="ghost" asChild><Link href={`/strategies/${s.id}/edit`}><Pencil aria-hidden /> Edit</Link></Button>}
      </CardFooter>
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={`Delete ${s.name}?`} confirmLabel="Delete" destructive
        onConfirm={() => void remove()} busy={action.busy} error={action.error}>
        <p>If it has trades or tests, it is archived instead so your history stays complete. Deactivate it everywhere first.</p>
      </ConfirmDialog>
      <EvaluationsSheet assignment={explain} onClose={() => setExplain(null)} />
    </Card>
  );
}
