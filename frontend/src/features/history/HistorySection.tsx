"use client";

import { Download, History, Inbox, ListChecks, OctagonX } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import { EnvBadge } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { PnlText } from "@/components/app/money";
import { EmptyState, ErrorState, ListSkeleton, Notice } from "@/components/app/states";
import { SectionTabs } from "@/components/layout/SectionTabs";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useLiveRefresh } from "@/components/providers/LiveProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Account, JournalEvent, Order, Paginated, Strategy, Trade } from "@/lib/types";
import { detectPreset, EMPTY_FILTERS, exportUrl, historyQuery, type HistoryFilters, OUTCOME_OPTIONS, presetRange, type RangePreset, rangeProblem } from "./filters";
import { TradeDetailSheet } from "./TradeDetailSheet";
import { TradeList } from "./TradeList";

export const HISTORY_TABS = ["open", "closed", "activity"] as const;

const ALL = "all";

/** HISTORY — open trades, finished trades (with filters + CSV), and every decision the bot made. */
export function HistorySection() {
  const { account } = useAppData();
  // Default to the account selected in the top bar; "All accounts" is one click away.
  const [state, setState] = useState<{ filters: HistoryFilters; accountChosen: boolean }>(() => ({ filters: { ...EMPTY_FILTERS, ...presetRange("30d") }, accountChosen: false }));
  // Until the user picks an account filter, follow the account selected in the top bar.
  const filters = state.accountChosen ? state.filters : { ...state.filters, accountId: account?.id ?? "" };
  const setFilters = (next: HistoryFilters) => setState({ filters: next, accountChosen: state.accountChosen || next.accountId !== filters.accountId });
  const [tradeId, setTradeId] = useState<string | null>(null);
  return (
    <>
      <SectionTabs
        title="History"
        description="What is open now, what has finished, and every decision the bot made."
        tabs={[
          { value: "open", label: "Open", content: <OpenTab filters={filters} setFilters={setFilters} onSelect={setTradeId} /> },
          { value: "closed", label: "Closed", content: <ClosedTab filters={filters} setFilters={setFilters} onSelect={setTradeId} /> },
          { value: "activity", label: "Activity", content: <ActivityTab filters={filters} setFilters={setFilters} /> },
        ]}
      />
      <TradeDetailSheet tradeId={tradeId} onClose={() => setTradeId(null)} />
    </>
  );
}

interface TabProps {
  filters: HistoryFilters;
  setFilters: (f: HistoryFilters) => void;
}

function AccountFilter({ filters, setFilters }: TabProps) {
  const { accounts } = useAppData();
  return (
    <div className="grid gap-1.5">
      <Label htmlFor="history-account">Account</Label>
      <Select value={filters.accountId || ALL} onValueChange={(v) => v && setFilters({ ...filters, accountId: v === ALL ? "" : v })}>
        <SelectTrigger id="history-account" className="w-full sm:w-56"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All accounts</SelectItem>
          {(accounts ?? []).map((a: Account) => (
            <SelectItem key={a.id} value={a.id}>{a.label} · {a.environment}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

// ── Open ────────────────────────────────────────────────────────────────

function OpenTab({ filters, setFilters, onSelect }: TabProps & { onSelect: (id: string) => void }) {
  const { live, reloadStatus } = useAppData();
  const positions = useApi<Trade[]>("/positions", { account_id: filters.accountId || undefined }, live ? 30_000 : 4000);
  const reload = positions.reload;
  useLiveRefresh(["trade.opened", "trade.closed"], useCallback(() => void reload(), [reload]));
  const [confirm, setConfirm] = useState(false);
  const action = useAction();
  const list = positions.data;

  const closeAll = async () => {
    const result = await action.run(() => api<{ closed?: number; failed?: unknown[] }>("/trading/close-positions", { method: "POST", body: { confirm: true, reason: "Close all from History" } }));
    if (result) {
      setConfirm(false);
      toast.success("Trading stopped and open trades closed", { description: `${result.closed ?? 0} closed${result.failed?.length ? `, ${result.failed.length} could not be closed (see notifications)` : ""}.` });
      await Promise.all([reload(), reloadStatus()]);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <AccountFilter filters={filters} setFilters={setFilters} />
        {list && list.length > 0 && (
          <Button variant="outline" className="border-negative/40 text-negative hover:bg-negative-soft hover:text-negative" onClick={() => { action.reset(); setConfirm(true); }}>
            <OctagonX aria-hidden /> Close all open trades…
          </Button>
        )}
      </div>
      {positions.error && !list ? <ErrorState message={positions.error} onRetry={() => void reload()} />
        : !list ? <ListSkeleton rows={3} />
          : list.length === 0 ? (
            <Card><EmptyState icon={Inbox} title="No open trades" action={<Button asChild variant="outline"><Link href="/">Back to Home</Link></Button>}>
              When an active strategy opens a trade it shows up here with its time left and current profit or loss.
            </EmptyState></Card>
          ) : (
            <>
              <p className="text-sm text-fg-muted" aria-live="polite"><span className="font-bold text-fg">{list.length} open</span> · current P/L <PnlTotal trades={list} open /></p>
              <TradeList trades={list} open onSelect={onSelect} showAccount={!filters.accountId} />
            </>
          )}
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Close every open trade?" confirmLabel="Stop and close all" destructive
        onConfirm={() => void closeAll()} busy={action.busy} error={action.error}>
        <p>This stops your trading first, then asks the broker to close every open trade on your accounts at the current price.</p>
        <p>Rise/Fall contracts can&apos;t be closed early — they finish at expiry on their own.</p>
      </ConfirmDialog>
    </div>
  );
}

function PnlTotal({ trades, open }: { trades: Trade[]; open?: boolean }) {
  const currencies = new Set(trades.map((t) => t.account?.currency ?? ""));
  if (currencies.size !== 1) return <span className="text-fg-subtle">(mixed currencies)</span>;
  const total = trades.reduce((sum, t) => sum + Number((open ? t.unrealized_pnl : t.net_pnl) ?? 0), 0);
  return <PnlText value={total} currency={[...currencies][0]} className="font-bold" />;
}

// ── Closed ──────────────────────────────────────────────────────────────

const PRESETS: { value: RangePreset; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "all", label: "All time" },
  { value: "custom", label: "Custom dates" },
];

function ClosedTab({ filters, setFilters, onSelect }: TabProps & { onSelect: (id: string) => void }) {
  const { live } = useAppData();
  const [page, setPage] = useState(1);
  const update = (next: HistoryFilters) => {
    setPage(1);
    setFilters(next);
  };
  const problem = rangeProblem(filters);
  const history = useApi<Paginated<Trade>>(problem ? null : "/history", historyQuery(filters, { page, per_page: 50 }), live ? 60_000 : 15_000);
  const reload = history.reload;
  useLiveRefresh(["trade.closed"], useCallback(() => void reload(), [reload]));
  const strategies = useApi<Strategy[]>("/strategies");
  const preset = detectPreset(filters);
  const [custom, setCustom] = useState(preset === "custom");
  const strategyOptions = useMemo(() => (strategies.data ?? []).filter((s) => !s.built_in || s.assignments.length > 0), [strategies.data]);
  const data = history.data;

  return (
    <div className="space-y-4">
      <Card size="sm" className="bg-surface-raised shadow-none">
        <CardContent>
          <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" onSubmit={(e) => e.preventDefault()} aria-label="Filters">
            <div className="grid gap-1.5">
              <Label htmlFor="history-range">Period</Label>
              <Select value={custom ? "custom" : preset} onValueChange={(v) => {
                const p = v as RangePreset;
                setCustom(p === "custom");
                if (p !== "custom") update({ ...filters, ...presetRange(p) });
              }}>
                <SelectTrigger id="history-range" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>{PRESETS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            {custom && (
              <>
                <div className="grid gap-1.5">
                  <Label htmlFor="history-from">From</Label>
                  <Input id="history-from" type="date" value={filters.from} onChange={(e) => update({ ...filters, from: e.target.value })} aria-invalid={Boolean(problem)} />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="history-to">To</Label>
                  <Input id="history-to" type="date" value={filters.to} onChange={(e) => update({ ...filters, to: e.target.value })} aria-invalid={Boolean(problem)} />
                </div>
              </>
            )}
            <AccountFilter filters={filters} setFilters={update} />
            <div className="grid gap-1.5">
              <Label htmlFor="history-strategy">Strategy</Label>
              <Select value={filters.strategyId || ALL} onValueChange={(v) => update({ ...filters, strategyId: v === ALL ? "" : v })}>
                <SelectTrigger id="history-strategy" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All strategies</SelectItem>
                  {strategyOptions.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="history-outcome">Result</Label>
              <Select value={filters.outcome || ALL} onValueChange={(v) => update({ ...filters, outcome: v === ALL ? "" : (v as HistoryFilters["outcome"]) })}>
                <SelectTrigger id="history-outcome" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {OUTCOME_OPTIONS.map((o) => <SelectItem key={o.value || ALL} value={o.value || ALL}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </form>
          {problem && <p role="alert" className="mt-2 text-sm text-negative">{problem}</p>}
        </CardContent>
      </Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-fg-muted" aria-live="polite">
          {data ? <>{data.total.toLocaleString()} finished trade{data.total === 1 ? "" : "s"}{data.data.length > 0 && <> · this page <PnlTotal trades={data.data} /></>}</> : " "}
        </p>
        {problem ? (
          <Button variant="outline" disabled><Download aria-hidden /> Export CSV</Button>
        ) : (
          <Button variant="outline" asChild>
            <a href={exportUrl(filters)} download onClick={() => toast.success("Exporting CSV", { description: "Your download starts in a moment." })}>
              <Download aria-hidden /> Export CSV
            </a>
          </Button>
        )}
      </div>
      {history.error && !data ? <ErrorState message={history.error} onRetry={() => void reload()} />
        : !data ? <ListSkeleton rows={5} />
          : data.data.length === 0 ? (
            <Card><EmptyState icon={History} title="No finished trades match" action={<Button variant="outline" onClick={() => { setCustom(false); update({ ...EMPTY_FILTERS }); }}>Clear filters</Button>}>
              Try a longer period or another account. Trades appear here once they finish.
            </EmptyState></Card>
          ) : (
            <>
              <TradeList trades={data.data} onSelect={onSelect} showAccount={!filters.accountId} />
              {data.last_page > 1 && (
                <nav className="flex items-center justify-between gap-3" aria-label="Pages">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
                  <span className="num text-sm text-fg-muted">Page {data.current_page} of {data.last_page}</span>
                  <Button variant="outline" size="sm" disabled={page >= data.last_page} onClick={() => setPage(page + 1)}>Next</Button>
                </nav>
              )}
            </>
          )}
    </div>
  );
}

// ── Activity ────────────────────────────────────────────────────────────

const EVENT_TONE: Record<string, string> = {
  SIGNAL: "bg-info",
  RISK_REJECTED: "bg-warning",
  ORDER_FILLED: "bg-positive",
  POSITION_CLOSED: "bg-primary",
};

function ActivityTab({ filters, setFilters }: TabProps) {
  const { live } = useAppData();
  const [view, setView] = useState<"decisions" | "orders">("decisions");
  const journal = useApi<Paginated<JournalEvent>>(view === "decisions" ? "/journal" : null, { account_id: filters.accountId || undefined, per_page: 100 }, live ? 60_000 : 10_000);
  const orders = useApi<Paginated<Order>>(view === "orders" ? "/orders" : null, { account_id: filters.accountId || undefined, per_page: 100 }, live ? 60_000 : 10_000);
  const reloadJournal = journal.reload;
  const reloadOrders = orders.reload;
  useLiveRefresh(["trade.opened", "trade.closed"], useCallback(() => { void reloadJournal(); void reloadOrders(); }, [reloadJournal, reloadOrders]));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <AccountFilter filters={filters} setFilters={setFilters} />
        <div role="group" aria-label="Show" className="inline-flex gap-2">
          {(["decisions", "orders"] as const).map((v) => (
            <Button key={v} size="sm" variant="secondary" aria-pressed={view === v} onClick={() => setView(v)}
              className={view === v ? "bg-foreground text-background hover:bg-foreground" : "bg-muted dark:bg-[#2a2a2a]"}>
              {v === "decisions" ? "Bot decisions" : "Orders"}
            </Button>
          ))}
        </div>
      </div>
      {view === "decisions" ? (
        journal.error && !journal.data ? <ErrorState message={journal.error} onRetry={() => void reloadJournal()} />
          : !journal.data ? <ListSkeleton rows={5} />
            : journal.data.data.length === 0 ? (
              <Card><EmptyState icon={ListChecks} title="No activity yet">Every signal, risk decision, order and exit is written here as the bot works — including trades it decided not to take, and why.</EmptyState></Card>
            ) : (
              <Card>
                <CardContent>
                  <ol className="divide-y divide-line">
                    {journal.data.data.map((e) => (
                      <li key={e.id} className="relative flex gap-3 py-3 first:pt-0 last:pb-0">
                        <span className={`mt-1.5 size-2.5 shrink-0 rounded-full ring-4 ring-card ${EVENT_TONE[e.event_type] ?? "bg-fg-subtle"}`} aria-hidden />
                        <div className="min-w-0">
                          <p className="text-sm text-fg">{e.message}</p>
                          <p className="mt-0.5 text-xs text-fg-subtle"><span className="num">{formatDateTime(e.occurred_at)}</span> · {humanize(e.event_type)}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </CardContent>
              </Card>
            )
      ) : (
        orders.error && !orders.data ? <ErrorState message={orders.error} onRetry={() => void reloadOrders()} />
          : !orders.data ? <ListSkeleton rows={5} />
            : orders.data.data.length === 0 ? (
              <Card><EmptyState icon={ListChecks} title="No orders yet">Orders are what 2kPilot sent to the broker to open or close trades.</EmptyState></Card>
            ) : (
              <Card>
                <CardContent>
                  <ul className="divide-y divide-line">
                    {orders.data.data.map((o) => (
                      <li key={o.id} className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0">
                        <div className="min-w-0">
                          <p className="text-sm text-fg">{o.purpose === "ENTRY" ? "Open" : "Close"} {o.symbol} · {o.side === "BUY" ? "Buy" : "Sell"}</p>
                          <p className="text-xs text-fg-subtle"><span className="num">{formatDateTime(o.created_at)}</span>{o.broker_message ? ` · ${o.broker_message}` : ""}</p>
                        </div>
                        <span className="flex items-center gap-2">
                          {o.account && <EnvBadge env={o.account.environment} />}
                          <span className={`text-xs font-medium ${o.status === "FILLED" ? "text-positive" : o.status === "REJECTED" || o.status === "FAILED" ? "text-negative" : "text-fg-muted"}`}>{humanize(o.status)}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )
      )}
      <Notice tone="info">Decisions the bot did <em>not</em> take are listed too, with the reason (for example a risk limit). Nothing here is ever deleted.</Notice>
    </div>
  );
}
