"use client";

import { BookOpen, History, ListOrdered, Wallet } from "lucide-react";
import { useState } from "react";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useSession } from "@/components/providers/SessionProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DataTable } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Segmented, TextInput } from "@/components/ui/Fields";
import { EmptyState, EnvBadge, Notice, Pnl, SideBadge } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { formatPnl, formatPrice, formatTime, humanize } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { JournalEvent, Order, Paginated, Signal, Trade } from "@/lib/types";
import { Checks, TradeDrawer } from "./TradeDrawer";

function useScope() {
  const { account } = useAppData();
  const [scope, setScope] = useState<"account" | "all">("account");
  return { account, scope, setScope, accountId: scope === "account" ? account?.id : undefined };
}

function ScopeToggle({ scope, setScope }: { scope: "account" | "all"; setScope: (s: "account" | "all") => void }) {
  return <Segmented size="sm" label="Accounts" value={scope} onChange={setScope} options={[{ value: "account", label: "This account" }, { value: "all", label: "All accounts" }]} />;
}

export function PositionsScreen() {
  const { scope, setScope, accountId } = useScope();
  const positions = useApi<Trade[]>("/positions", { account_id: accountId }, 3000);
  const { isOwner } = useSession();
  const [drawer, setDrawer] = useState<string | null>(null);
  const [closing, setClosing] = useState<Trade | null>(null);
  const [editing, setEditing] = useState<Trade | null>(null);
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const action = useAction();

  const close = async () => {
    if (!closing) return;
    const ok = await action.run(() => api(`/positions/${closing.id}/close`, { method: "POST", body: { confirm: true } }));
    if (ok !== null) { setClosing(null); void positions.reload(); }
  };
  const save = async () => {
    if (!editing) return;
    const ok = await action.run(() => api(`/positions/${editing.id}`, { method: "PUT", body: { stop_loss: sl, take_profit: tp || null } }));
    if (ok !== null) { setEditing(null); void positions.reload(); }
  };

  return (
    <div>
      <PageHeader title="Positions" description="Open trades, refreshed every few seconds. P/L is what the broker reports right now." actions={<ScopeToggle scope={scope} setScope={setScope} />} />
      <Card>
        <DataTable
          caption="Open positions"
          rows={positions.data}
          loading={positions.loading}
          error={positions.error}
          rowKey={(r) => r.id}
          onRowClick={(r) => setDrawer(r.id)}
          empty={<EmptyState icon={Wallet} title="No open positions">Positions opened by strategies or manual tickets appear here.</EmptyState>}
          columns={[
            { key: "symbol", header: "Symbol", cell: (r) => <span className="font-medium">{r.symbol}</span> },
            { key: "side", header: "Side", cell: (r) => <SideBadge side={r.side} /> },
            { key: "account", header: "Account", hideBelow: "lg", cell: (r) => r.account && <span className="flex items-center gap-2 text-fg-muted">{r.account.label} <EnvBadge env={r.account.environment} /></span> },
            { key: "source", header: "Source", hideBelow: "md", cell: (r) => <span className="text-fg-muted">{r.source === "STRATEGY" ? r.strategy : humanize(r.source)}</span> },
            { key: "volume", header: "Volume", align: "right", cell: (r) => Number(r.volume).toString() },
            { key: "entry", header: "Entry", align: "right", hideBelow: "sm", cell: (r) => formatPrice(r.entry_price, r.symbol) },
            { key: "sl", header: "Stop", align: "right", hideBelow: "md", cell: (r) => formatPrice(r.stop_loss, r.symbol) },
            { key: "tp", header: "Target", align: "right", hideBelow: "md", cell: (r) => formatPrice(r.take_profit, r.symbol) },
            { key: "pnl", header: "P/L", align: "right", cell: (r) => <Pnl value={r.unrealized_pnl}>{formatPnl(r.unrealized_pnl, r.account?.currency)}</Pnl> },
            { key: "actions", header: <span className="sr-only">Actions</span>, align: "right", cell: (r) => isOwner && (
              <span className="flex justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                <Button size="sm" variant="ghost" onClick={() => { setEditing(r); setSl(r.stop_loss ?? ""); setTp(r.take_profit ?? ""); action.reset(); }}>Edit</Button>
                <Button size="sm" variant="danger-outline" onClick={() => { setClosing(r); action.reset(); }}>Close</Button>
              </span>
            ) },
          ]}
        />
      </Card>
      <TradeDrawer tradeId={drawer} onClose={() => setDrawer(null)} />
      <ConfirmDialog open={closing !== null} title={`Close ${closing?.side} ${closing?.symbol}?`} confirmLabel="Close position" confirmVariant="danger" busy={action.busy} error={action.error}
        onCancel={() => setClosing(null)} onConfirm={() => void close()}>
        <p>Closes the whole position at the current market price ({closing?.account?.environment}).</p>
      </ConfirmDialog>
      <Dialog open={editing !== null} onClose={() => setEditing(null)} title={`Edit ${editing?.symbol}`}
        footer={<><Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button><Button variant="primary" onClick={() => void save()} disabled={action.busy || !sl}>Save</Button></>}>
        <div className="space-y-4">
          <Field label="Stop loss" hint="A stop loss can be moved, never removed."><TextInput value={sl} onChange={(e) => setSl(e.target.value)} className="num" /></Field>
          <Field label="Take profit" hint="Leave empty for none."><TextInput value={tp} onChange={(e) => setTp(e.target.value)} className="num" /></Field>
          {action.error && <Notice tone="danger">{action.error}</Notice>}
        </div>
      </Dialog>
    </div>
  );
}

export function OrdersScreen() {
  const { scope, setScope, accountId } = useScope();
  const orders = useApi<Paginated<Order>>("/orders", { account_id: accountId, per_page: 100 }, 5000);
  return (
    <div>
      <PageHeader title="Orders" description="Every instruction sent — or about to be sent — to a broker. Uncertain outcomes are reconciled with the broker, never blindly re-sent." actions={<ScopeToggle scope={scope} setScope={setScope} />} />
      <Card>
        <DataTable
          caption="Orders"
          rows={orders.data?.data ?? null}
          loading={orders.loading}
          error={orders.error}
          rowKey={(r) => r.id}
          empty={<EmptyState icon={ListOrdered} title="No orders yet" />}
          columns={[
            { key: "time", header: "Created", cell: (r) => <span className="text-fg-muted">{formatTime(r.created_at)}</span> },
            { key: "symbol", header: "Symbol", cell: (r) => <span className="font-medium">{r.symbol}</span> },
            { key: "side", header: "Side", cell: (r) => <SideBadge side={r.side} /> },
            { key: "purpose", header: "Purpose", hideBelow: "sm", cell: (r) => <span className="text-fg-muted">{r.purpose === "ENTRY" ? "Open" : "Close"} · {r.order_type.toLowerCase()}</span> },
            { key: "volume", header: "Volume", align: "right", cell: (r) => Number(r.volume).toString() },
            { key: "fill", header: "Fill", align: "right", hideBelow: "md", cell: (r) => formatPrice(r.fill_price, r.symbol) },
            { key: "status", header: "Status", cell: (r) => <Badge tone={r.status === "FILLED" ? "positive" : ["REJECTED", "FAILED"].includes(r.status) ? "negative" : r.status === "UNKNOWN" ? "warning" : "neutral"}>{humanize(r.status)}</Badge> },
            { key: "env", header: "Account", hideBelow: "lg", cell: (r) => r.account && <EnvBadge env={r.account.environment} /> },
            { key: "msg", header: "Broker message", hideBelow: "lg", cell: (r) => <span className="text-xs text-fg-subtle">{r.broker_message ?? "—"}</span> },
          ]}
        />
      </Card>
    </div>
  );
}

export function HistoryScreen() {
  const { scope, setScope, accountId } = useScope();
  const [page, setPage] = useState(1);
  const history = useApi<Paginated<Trade>>("/history", { account_id: accountId, page, per_page: 50 });
  const [drawer, setDrawer] = useState<string | null>(null);
  return (
    <div>
      <PageHeader title="History" description="Closed trades. Click a trade to see the full chain from signal to P/L." actions={<ScopeToggle scope={scope} setScope={setScope} />} />
      <Card>
        <DataTable
          caption="Trade history"
          rows={history.data?.data ?? null}
          loading={history.loading}
          error={history.error}
          rowKey={(r) => r.id}
          onRowClick={(r) => setDrawer(r.id)}
          empty={<EmptyState icon={History} title="No closed trades yet" />}
          columns={[
            { key: "time", header: "Closed", cell: (r) => <span className="text-fg-muted">{formatTime(r.exit_time)}</span> },
            { key: "symbol", header: "Symbol", cell: (r) => <span className="font-medium">{r.symbol}</span> },
            { key: "side", header: "Side", cell: (r) => <SideBadge side={r.side} /> },
            { key: "source", header: "Source", hideBelow: "md", cell: (r) => <span className="text-fg-muted">{r.source === "STRATEGY" ? r.strategy : humanize(r.source)}</span> },
            { key: "env", header: "Account", hideBelow: "lg", cell: (r) => r.account && <EnvBadge env={r.account.environment} /> },
            { key: "exit", header: "Exit", hideBelow: "sm", cell: (r) => <span className="text-fg-muted">{r.exit_reason ? humanize(r.exit_reason) : "—"}</span> },
            { key: "r", header: "R", align: "right", hideBelow: "sm", cell: (r) => (r.r_multiple ? Number(r.r_multiple).toFixed(2) : "—") },
            { key: "pnl", header: "Net P/L", align: "right", cell: (r) => <Pnl value={r.net_pnl}>{formatPnl(r.net_pnl, r.account?.currency)}</Pnl> },
          ]}
        />
        {history.data && history.data.last_page > 1 && (
          <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-fg-muted">
            <span>Page {history.data.current_page} of {history.data.last_page} · {history.data.total} trades</span>
            <span className="flex gap-2">
              <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <Button size="sm" disabled={page >= history.data.last_page} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </span>
          </div>
        )}
      </Card>
      <TradeDrawer tradeId={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}

export function JournalScreen() {
  const { scope, setScope, accountId } = useScope();
  const [view, setView] = useState<"events" | "decisions">("decisions");
  const events = useApi<Paginated<JournalEvent>>(view === "events" ? "/journal" : null, { account_id: accountId, per_page: 150 }, 5000);
  const signals = useApi<Paginated<Signal>>(view === "decisions" ? "/signals" : null, { account_id: accountId, per_page: 100 }, 5000);
  const [open, setOpen] = useState<Signal | null>(null);
  return (
    <div>
      <PageHeader title="Journal" description="Every decision is traceable: signal → risk decision → order → broker response → position → exit. Rejected signals are kept with their reasons."
        actions={<><Segmented size="sm" label="View" value={view} onChange={setView} options={[{ value: "decisions", label: "Decisions" }, { value: "events", label: "All events" }]} /><ScopeToggle scope={scope} setScope={setScope} /></>} />
      <Card>
        {view === "decisions" ? (
          <DataTable
            caption="Signals and risk decisions"
            rows={signals.data?.data ?? null}
            loading={signals.loading}
            error={signals.error}
            rowKey={(r) => r.id}
            onRowClick={setOpen}
            empty={<EmptyState icon={BookOpen} title="No decisions yet">Signals from strategies and manual tickets appear here with the risk engine&apos;s verdict.</EmptyState>}
            columns={[
              { key: "time", header: "Time", cell: (r) => <span className="text-fg-muted">{formatTime(r.created_at)}</span> },
              { key: "source", header: "Source", cell: (r) => <span className="text-fg-muted">{r.source === "MANUAL" ? "Manual" : r.version?.strategy?.name ?? "Strategy"}</span> },
              { key: "symbol", header: "Signal", cell: (r) => <span><SideBadge side={r.side} /> <span className="font-medium">{r.symbol}</span></span> },
              { key: "status", header: "Decision", cell: (r) => <Badge tone={r.status === "EXECUTED" ? "positive" : r.status === "REJECTED" ? "warning" : r.status === "FAILED" ? "negative" : "neutral"}>{humanize(r.status)}</Badge> },
              { key: "why", header: "Why", cell: (r) => <span className="line-clamp-1 text-xs text-fg-muted">{r.rejection_reason ?? r.reasons.join("; ")}</span> },
            ]}
          />
        ) : (
          <ol className="divide-y divide-line">
            {(events.data?.data ?? []).map((e) => (
              <li key={e.id} className="flex gap-4 px-4 py-2.5 text-sm">
                <span className="num w-28 shrink-0 text-xs text-fg-subtle">{formatTime(e.occurred_at)}</span>
                <span className="w-36 shrink-0 text-xs font-medium text-fg-muted">{humanize(e.event_type)}</span>
                <span className="min-w-0 text-fg">{e.message}</span>
              </li>
            ))}
            {events.data?.data.length === 0 && <li className="px-4 py-10 text-center text-sm text-fg-subtle">No journal events yet.</li>}
          </ol>
        )}
      </Card>
      <Dialog open={open !== null} onClose={() => setOpen(null)} variant="drawer" title={open ? `${open.side} ${open.symbol} — ${humanize(open.status)}` : ""}>
        {open && (
          <div className="space-y-5">
            {open.rejection_reason && <Notice tone="warning" title="Why it was not traded">{open.rejection_reason}</Notice>}
            <div><h3 className="mb-2 text-sm font-semibold">Strategy reasons</h3><ul className="list-disc space-y-1 pl-5 text-sm text-fg-muted">{open.reasons.map((r) => <li key={r}>{r}</li>)}</ul></div>
            <div><h3 className="mb-2 text-sm font-semibold">Risk checks</h3>{open.risk_checks.length ? <Checks items={open.risk_checks} /> : <p className="text-sm text-fg-muted">—</p>}</div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
