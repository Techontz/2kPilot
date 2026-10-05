"use client";

import { Pause, Play, Plus, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useSession } from "@/components/providers/SessionProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Select, TextInput } from "@/components/ui/Fields";
import { EmptyState, EnvBadge, Loading, Notice, Pnl } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDate, formatPct, formatPnl, formatRelative, formatTime } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Assignment, Evaluation, Instrument, Paginated, Signal, Strategy } from "@/lib/types";
import { Checks } from "../records/TradeDrawer";
import { ParamsEditor } from "./ParamsEditor";

/**
 * A strategy turns closed candles into signals. It never talks to a broker:
 * market data → strategy → signal → risk engine → execution engine → broker adapter → broker.
 */
export function StrategiesScreen() {
  const strategies = useApi<Strategy[]>("/strategies", undefined, 15000);
  if (!strategies.data) return strategies.error ? <Notice tone="danger">{strategies.error}</Notice> : <Loading />;
  return (
    <div>
      <PageHeader title="Strategies" description="Strategies propose trades; the risk engine decides. Versions are immutable — changing parameters creates a new version, and assignments start paused." />
      {strategies.data.length === 0 ? (
        <Card><EmptyState icon={SlidersHorizontal} title="No strategies registered yet">The trading engine registers its built-in strategies when it starts. Start it with <code className="num">make dev</code>.</EmptyState></Card>
      ) : (
        <div className="space-y-6">{strategies.data.map((s) => <StrategyCard key={s.id} strategy={s} onChange={() => void strategies.reload()} />)}</div>
      )}
    </div>
  );
}

function StrategyCard({ strategy, onChange }: { strategy: Strategy; onChange: () => void }) {
  const { isOwner } = useSession();
  const [assignOpen, setAssignOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const [explain, setExplain] = useState<Assignment | null>(null);
  const action = useAction();
  const latest = strategy.versions[strategy.versions.length - 1];
  const bt = strategy.last_backtest?.metrics;

  const setStatus = (a: Assignment, enable: boolean) =>
    action.run(() => api(`/assignments/${a.id}/${enable ? "enable" : "pause"}`, { method: "POST", body: {} })).then((r) => r !== null && onChange());
  const switchVersion = (a: Assignment, versionId: string) =>
    action.run(() => api(`/assignments/${a.id}/version`, { method: "PUT", body: { strategy_version_id: versionId } })).then((r) => r !== null && onChange());
  const remove = (a: Assignment) => action.run(() => api(`/assignments/${a.id}`, { method: "DELETE" })).then((r) => r !== null && onChange());

  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2">{strategy.name} {strategy.code_version && <Badge tone="neutral">code {strategy.code_version}</Badge>}</span>}
        description={strategy.description}
        action={isOwner && (
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => setVersionOpen(true)} disabled={!strategy.parameter_schema}>New version</Button>
            <Button size="sm" variant="primary" onClick={() => setAssignOpen(true)}><Plus className="size-3.5" aria-hidden /> Assign</Button>
          </div>
        )}
      />
      <CardBody className="grid gap-4 border-b border-line sm:grid-cols-4">
        <Stat label="Versions" value={String(strategy.versions.length)} hint={latest ? `latest v${latest.version} · ${formatDate(latest.created_at)}` : undefined} />
        <Stat label="Closed trades (live/paper)" value={String(strategy.live_trades)} />
        <Stat label="Net P/L (all accounts)" value={<Pnl value={strategy.live_net_pnl}>{formatPnl(strategy.live_net_pnl)}</Pnl>} hint="Mixed currencies are not converted" />
        <Stat label="Last backtest" value={bt ? formatPct(bt.return_pct, 2, true) : "—"} hint={bt ? `${bt.trades} trades · PF ${bt.profit_factor ?? "—"} · historical` : "Run one in Backtesting"} />
      </CardBody>
      {action.error && <Notice tone="danger" className="m-4">{action.error}</Notice>}
      <DataTable
        caption={`${strategy.name} assignments`}
        rows={strategy.assignments}
        rowKey={(r) => r.id}
        empty={<span>Not assigned to any account. {isOwner && "Use “Assign” to run it on a paper account first."}</span>}
        columns={[
          { key: "account", header: "Account", cell: (a) => a.account && <span className="flex items-center gap-2">{a.account.label} <EnvBadge env={a.account.environment} /></span> },
          { key: "symbol", header: "Symbol", cell: (a) => <span className="font-medium">{a.symbol}</span> },
          { key: "version", header: "Version", cell: (a) => isOwner ? (
            <Select aria-label="Version" className="h-8 w-24" value={a.strategy_version_id} onChange={(e) => void switchVersion(a, e.target.value)}>
              {strategy.versions.map((v) => <option key={v.id} value={v.id}>v{v.version}</option>)}
            </Select>
          ) : `v${a.version}` },
          { key: "status", header: "Status", cell: (a) => <Badge tone={a.status === "ENABLED" ? "positive" : "neutral"} dot>{a.status === "ENABLED" ? "Enabled" : "Paused"}</Badge> },
          { key: "reason", header: "Last check", hideBelow: "md", cell: (a) => <span className="text-xs text-fg-subtle">{a.last_bar_evaluated ? `bar ${formatTime(a.last_bar_evaluated)}` : a.status_reason ?? "—"}</span> },
          { key: "actions", header: <span className="sr-only">Actions</span>, align: "right", cell: (a) => (
            <span className="flex justify-end gap-1.5">
              <Button size="sm" variant="ghost" onClick={() => setExplain(a)}>Why?</Button>
              {isOwner && (a.status === "ENABLED"
                ? <Button size="sm" onClick={() => void setStatus(a, false)}><Pause className="size-3.5" aria-hidden /> Pause</Button>
                : <Button size="sm" onClick={() => void setStatus(a, true)}><Play className="size-3.5 text-positive" aria-hidden /> Enable</Button>)}
              {isOwner && a.status === "PAUSED" && <Button size="sm" variant="ghost" onClick={() => void remove(a)}>Remove</Button>}
            </span>
          ) },
        ]}
      />
      <AssignDialog open={assignOpen} strategy={strategy} onClose={() => setAssignOpen(false)} onDone={() => { setAssignOpen(false); onChange(); }} />
      {strategy.parameter_schema && latest && (
        <VersionDialog open={versionOpen} strategy={strategy} onClose={() => setVersionOpen(false)} onDone={() => { setVersionOpen(false); onChange(); }} />
      )}
      <ExplainDrawer assignment={explain} onClose={() => setExplain(null)} />
    </Card>
  );
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-fg-subtle">{label}</p>
      <p className="num mt-1 text-base font-semibold text-fg">{value}</p>
      {hint && <p className="mt-0.5 truncate text-xs text-fg-subtle">{hint}</p>}
    </div>
  );
}

function AssignDialog({ open, strategy, onClose, onDone }: { open: boolean; strategy: Strategy; onClose: () => void; onDone: () => void }) {
  const { accounts, account } = useAppData();
  const [accountId, setAccountId] = useState(account?.id ?? "");
  const [versionId, setVersionId] = useState(strategy.versions[strategy.versions.length - 1]?.id ?? "");
  const [symbol, setSymbol] = useState("");
  const instruments = useApi<{ instruments: Instrument[] }>(open && accountId ? "/markets/instruments" : null, { account_id: accountId });
  const action = useAction();
  const submit = async () => {
    const ok = await action.run(() => api("/assignments", { method: "POST", body: { account_id: accountId, strategy_version_id: versionId, symbol } }));
    if (ok !== null) onDone();
  };
  return (
    <Dialog open={open} onClose={onClose} title={`Assign ${strategy.name}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!accountId || !symbol || action.busy} onClick={() => void submit()}>Assign (paused)</Button></>}>
      <div className="space-y-4">
        <Field label="Account">
          <Select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Choose…</option>
            {accounts?.map((a) => <option key={a.id} value={a.id}>{a.label} — {a.environment}</option>)}
          </Select>
        </Field>
        <Field label="Symbol">
          <Select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            <option value="">Choose…</option>
            {instruments.data?.instruments.filter((i) => i.trade_allowed).map((i) => <option key={i.name} value={i.name}>{i.canonical} — {i.description}</option>)}
          </Select>
        </Field>
        <Field label="Version">
          <Select value={versionId} onChange={(e) => setVersionId(e.target.value)}>
            {strategy.versions.map((v) => <option key={v.id} value={v.id}>v{v.version} — {v.notes || "no notes"}</option>)}
          </Select>
        </Field>
        <p className="text-sm text-fg-muted">The assignment starts <strong className="text-fg">paused</strong>. Enable it when you are ready; every signal still passes the risk engine.</p>
        {action.error && <Notice tone="danger">{action.error}</Notice>}
      </div>
    </Dialog>
  );
}

function VersionDialog({ open, strategy, onClose, onDone }: { open: boolean; strategy: Strategy; onClose: () => void; onDone: () => void }) {
  const latest = strategy.versions[strategy.versions.length - 1]!;
  const [params, setParams] = useState<Record<string, unknown>>(latest.parameters);
  const [notes, setNotes] = useState("");
  const action = useAction();
  const submit = async () => {
    const ok = await action.run(() => api(`/strategies/${strategy.id}/versions`, { method: "POST", body: { parameters: params, notes } }));
    if (ok !== null) onDone();
  };
  return (
    <Dialog open={open} onClose={onClose} size="xl" title={`New version of ${strategy.name}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={action.busy} onClick={() => void submit()}>Create v{latest.version + 1}</Button></>}>
      <div className="space-y-5">
        <p className="text-sm text-fg-muted">Starting from v{latest.version}. Existing versions never change, so past trades and backtests stay reproducible.</p>
        <ParamsEditor schema={strategy.parameter_schema!} value={params} onChange={setParams} />
        <Field label="Notes"><TextInput value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} placeholder="What changed and why" /></Field>
        {action.error && <Notice tone="danger">{action.error}</Notice>}
      </div>
    </Dialog>
  );
}

function ExplainDrawer({ assignment, onClose }: { assignment: Assignment | null; onClose: () => void }) {
  const data = useApi<{ evaluations: Paginated<Evaluation>; signals: Signal[] }>(assignment ? `/assignments/${assignment.id}/evaluations` : null, undefined, 10000);
  return (
    <Dialog open={assignment !== null} onClose={onClose} variant="drawer" title={assignment ? `Why ${assignment.symbol} did — or didn't — trade` : ""}>
      {!data.data ? <Loading /> : (
        <div className="space-y-6">
          <section>
            <h3 className="mb-2 text-sm font-semibold">Recent signals and risk decisions</h3>
            {data.data.signals.length === 0 ? <p className="text-sm text-fg-muted">No signals yet.</p> : (
              <ul className="space-y-2">
                {data.data.signals.map((s) => (
                  <li key={s.id} className="rounded-lg border border-line px-3 py-2 text-sm">
                    <p className="flex items-center justify-between gap-2"><span className="text-fg">{s.side} · bar {formatTime(s.bar_time)}</span>
                      <Badge tone={s.status === "EXECUTED" ? "positive" : s.status === "REJECTED" ? "warning" : "neutral"}>{s.status.toLowerCase()}</Badge></p>
                    <p className="mt-1 text-xs text-fg-muted">{s.rejection_reason ?? s.reasons.join("; ")}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <h3 className="mb-2 text-sm font-semibold">Every closed bar</h3>
            <ul className="space-y-3">
              {data.data.evaluations.data.map((e) => (
                <li key={e.id} className="rounded-lg border border-line px-3 py-2.5">
                  <p className="flex items-center justify-between gap-2 text-sm">
                    <span className="num text-xs text-fg-subtle">{formatTime(e.bar_time)} · {formatRelative(e.bar_time)}</span>
                    <span className={cn("text-xs font-medium", e.outcome === "SIGNAL" ? "text-positive" : e.outcome === "NO_SETUP" ? "text-fg-muted" : "text-warning")}>{e.outcome === "SIGNAL" ? "Signal" : e.outcome === "NO_SETUP" ? "No setup" : "Not enough data"}</span>
                  </p>
                  <p className="mt-1 text-sm text-fg">{e.summary}</p>
                  {e.checks.length > 0 && <div className="mt-2"><Checks items={e.checks.map((c) => ({ rule: c.name, passed: c.passed, detail: c.detail }))} /></div>}
                </li>
              ))}
              {data.data.evaluations.data.length === 0 && <p className="text-sm text-fg-muted">No bars evaluated yet. The robot checks each bar as it closes while trading is running.</p>}
            </ul>
          </section>
        </div>
      )}
    </Dialog>
  );
}
