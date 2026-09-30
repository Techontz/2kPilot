"use client";

import { Check, FlaskConical, Pause, Play, Plus, SlidersHorizontal, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Select, TextInput } from "@/components/ui/Fields";
import { EmptyState, EnvBadge, KeyValue, Loading, Notice, Pnl } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiRequest } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatPnl, formatTime, humanize } from "@/lib/format";
import type { Assignment, StrategyInfo, TradingAccount } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApiResource } from "@/lib/useApiResource";
import { ParamsForm, type ParamValues } from "./ParamsForm";

const OUTCOME_TONE = { SIGNAL: "positive", NO_SETUP: "neutral", INSUFFICIENT_DATA: "warning" } as const;

function EvaluationView({ a }: { a: Assignment }) {
  const ev = a.last_evaluation;
  if (!ev) return <p className="text-xs text-fg-subtle">Not evaluated yet — the engine evaluates on every newly closed bar while the assignment is enabled.</p>;
  return (
    <div>
      <p className="text-sm text-fg">
        <Badge tone={OUTCOME_TONE[ev.outcome]}>{humanize(ev.outcome)}</Badge> <span className="ml-1">{ev.summary}</span>
      </p>
      <p className="mt-0.5 text-xs text-fg-subtle">Bar {formatTime(ev.bar_time)}</p>
      {ev.checks.length > 0 && (
        <ul className="mt-2 space-y-1">
          {ev.checks.map((c, i) => (
            <li key={i} className="flex gap-2 text-xs">
              {c.passed ? <Check aria-label="passed" className="size-3.5 shrink-0 text-positive" /> : <X aria-label="failed" className="size-3.5 shrink-0 text-negative" />}
              <span className="text-fg-muted"><span className="text-fg">{c.name}</span> — {c.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssignDialog({ strategy, open, onClose, onDone }: { strategy: StrategyInfo; open: boolean; onClose: () => void; onDone: () => void }) {
  const accounts = useApiResource<TradingAccount[]>("/accounts", { enabled: open, refetchOnFocus: false });
  const [chosenAccount, setAccount] = useState("");
  const account = chosenAccount || accounts.data?.[0]?.id || "";
  const [symbol, setSymbol] = useState("");
  const [version, setVersion] = useState(strategy.versions.at(-1)?.id ?? "");
  const symbols = useApiResource<{ name: string }[]>(`/accounts/${account}/symbols`, { enabled: open && !!account, refetchOnFocus: false });
  const action = useAction();
  const submit = async () => {
    const res = await action.run(() => apiRequest("/strategies/assignments", { method: "POST", body: { strategy_version_id: version, account_id: account, symbol } }));
    if (res) onDone();
  };
  return (
    <Dialog open={open} onClose={onClose} title={`Assign ${strategy.name}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!account || !symbol || !version || action.busy} onClick={() => void submit()}>Assign (paused)</Button></>}>
      <div className="space-y-4">
        <Field label="Account">
          <Select value={account} onChange={(e) => { setAccount(e.target.value); setSymbol(""); }}>
            {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.label} · {a.environment}</option>)}
          </Select>
        </Field>
        <Field label="Symbol" hint="Symbols as named by this account's broker.">
          {symbols.data?.length ? (
            <Select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              <option value="">Choose…</option>
              {symbols.data.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
            </Select>
          ) : (
            <TextInput value={symbol} placeholder="EURUSD" onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
          )}
        </Field>
        <Field label="Version">
          <Select value={version} onChange={(e) => setVersion(e.target.value)}>
            {strategy.versions.map((v) => <option key={v.id} value={v.id}>v{v.version} {v.notes && `— ${v.notes}`}</option>)}
          </Select>
        </Field>
        <Notice tone="info">New assignments start PAUSED. A strategy never trades merely because it was assigned.</Notice>
        {action.error && <Notice tone="danger">{action.error}</Notice>}
      </div>
    </Dialog>
  );
}

function VersionDialog({ strategy, open, onClose, onDone }: { strategy: StrategyInfo; open: boolean; onClose: () => void; onDone: () => void }) {
  // Mounted only while open (see parent), so initial state always reflects the latest version.
  const [values, setValues] = useState<ParamValues>(() => ({ ...(strategy.versions.at(-1)?.parameters ?? {}) }));
  const [notes, setNotes] = useState("");
  const action = useAction();
  const submit = async () => {
    const res = await action.run(() => apiRequest(`/strategies/${strategy.id}/versions`, { method: "POST", body: { parameters: values, notes } }));
    if (res) onDone();
  };
  return (
    <Dialog open={open} onClose={onClose} size="xl" title={`New version of ${strategy.name}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={action.busy} onClick={() => void submit()}>Create v{(strategy.versions.at(-1)?.version ?? 0) + 1}</Button></>}>
      <div className="space-y-5">
        <Notice tone="info">Versions are immutable: every signal, trade and backtest records the exact version it used. Backtest a new version before enabling it.</Notice>
        <Field label="What changed and why?"><TextInput value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Tighter pullback zone" /></Field>
        <ParamsForm schema={strategy.parameter_schema} values={values} onChange={setValues} />
        {action.error && <Notice tone="danger">{action.error}</Notice>}
      </div>
    </Dialog>
  );
}

function AssignmentRow({ a, strategy, onChanged }: { a: Assignment; strategy: StrategyInfo; onChanged: () => void }) {
  const { isOwner } = useSession();
  const action = useAction();
  const call = (path: string, method: "POST" | "PUT" | "DELETE" = "POST", body?: unknown) =>
    void action.run(() => apiRequest(path, { method, body })).then((r) => r !== null && onChanged());
  return (
    <li className="space-y-3 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-fg">
            {a.symbol} on {a.account?.label ?? "—"} {a.account && <EnvBadge env={a.account.environment} />}
            <Badge tone={a.status === "ENABLED" ? "positive" : "neutral"} dot>{a.status === "ENABLED" ? "Enabled" : "Paused"}</Badge>
          </p>
          <p className="mt-0.5 text-xs text-fg-subtle">
            v{a.version} · {a.status_reason ?? ""}{a.account && !a.account.trading_enabled && " · account trading is off"}
          </p>
        </div>
        {isOwner && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Select aria-label="Version" value={a.strategy_version_id} className="h-8 w-auto text-xs"
              onChange={(e) => call(`/strategies/assignments/${a.id}/version`, "PUT", { strategy_version_id: e.target.value })}>
              {strategy.versions.map((v) => <option key={v.id} value={v.id}>v{v.version}</option>)}
            </Select>
            {a.status === "ENABLED" ? (
              <Button size="sm" onClick={() => call(`/strategies/assignments/${a.id}/pause`, "POST", { reason: "" })}><Pause aria-hidden className="size-3.5" />Pause</Button>
            ) : (
              <Button size="sm" variant="primary" onClick={() => call(`/strategies/assignments/${a.id}/enable`)}><Play aria-hidden className="size-3.5" />Enable</Button>
            )}
            <Button size="sm" variant="ghost" aria-label="Remove assignment" onClick={() => call(`/strategies/assignments/${a.id}`, "DELETE")}><Trash2 aria-hidden className="size-3.5" /></Button>
          </div>
        )}
      </div>
      <EvaluationView a={a} />
      {a.last_signal && (
        <p className="text-xs text-fg-subtle">
          Last signal: {a.last_signal.side} at {a.last_signal.entry_price} · {humanize(a.last_signal.status)} · {formatTime(a.last_signal.created_at)}
        </p>
      )}
      {action.error && <Notice tone="danger">{action.error}</Notice>}
    </li>
  );
}

export function StrategiesScreen() {
  const { isOwner } = useSession();
  const list = useApiResource<StrategyInfo[]>("/strategies");
  useLiveRefresh(["evaluation", "journal"], () => void list.reload(), 1500);
  const [selected, setSelected] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [versioning, setVersioning] = useState(false);
  const strategy = list.data?.find((s) => s.id === selected) ?? list.data?.[0] ?? null;
  const latest = strategy?.versions.at(-1);

  return (
    <>
      <PageHeader title="Strategies" description="Strategies propose trades from closed candles. They must be deliberately enabled per account and symbol, and the risk engine decides." />
      {!list.data && <Loading />}
      {list.data?.length === 0 && <Card><EmptyState icon={SlidersHorizontal} title="No strategies">The built-in strategy is created when the backend starts.</EmptyState></Card>}
      {list.data && list.data.length > 1 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {list.data.map((s) => (
            <button key={s.id} type="button" onClick={() => setSelected(s.id)} className={cn("rounded-lg border px-3 py-1.5 text-sm", strategy?.id === s.id ? "border-accent" : "border-line")}>{s.name}</button>
          ))}
        </div>
      )}
      {strategy && latest && (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <Card>
              <CardHeader
                title={<span className="flex items-center gap-2">{strategy.name}<Badge tone={strategy.status === "ENABLED" ? "positive" : "neutral"} dot>{strategy.status === "ENABLED" ? "Active" : "Paused"}</Badge></span>}
                description={`Code ${strategy.code_version} · ${strategy.timeframes.join(" entry / ")} context · ${strategy.versions.length} version(s)`}
                action={
                  <div className="flex gap-2">
                    <Link href={`/backtesting?version=${latest.id}`}><Button size="sm"><FlaskConical aria-hidden className="size-4" />Backtest</Button></Link>
                    {isOwner && <Button size="sm" variant="primary" onClick={() => setVersioning(true)}>New version</Button>}
                  </div>
                }
              />
              <CardBody>
                <p className="text-sm leading-relaxed text-fg-muted">{strategy.description}</p>
                <Notice tone="warning" className="mt-4">A research starting point. Nothing here is claimed to be profitable — prove it with out-of-sample backtests and demo trading first.</Notice>
              </CardBody>
            </Card>
            <Card>
              <CardHeader
                title="Accounts & markets"
                description="Where this strategy runs. Each row is evaluated on every newly closed bar while enabled."
                action={isOwner && <Button size="sm" onClick={() => setAssigning(true)}><Plus aria-hidden className="size-4" />Assign</Button>}
              />
              <CardBody className="py-0">
                {strategy.assignments.length === 0 ? (
                  <p className="py-6 text-sm text-fg-subtle">Not assigned to any account yet.</p>
                ) : (
                  <ul className="divide-y divide-line">
                    {strategy.assignments.map((a) => <AssignmentRow key={a.id} a={a} strategy={strategy} onChanged={() => void list.reload()} />)}
                  </ul>
                )}
              </CardBody>
            </Card>
          </div>
          <div className="space-y-6">
            <Card>
              <CardHeader title="Performance" description="Closed trades across all accounts." />
              <CardBody>
                <KeyValue items={[
                  ["Closed trades", strategy.performance.closed_trades],
                  ["Net P/L", <Pnl key="p" value={strategy.performance.net_pnl}>{formatPnl(strategy.performance.net_pnl)}</Pnl>],
                  ["Last trade", strategy.last_trade ? formatTime(strategy.last_trade.entry_time) : "—"],
                  ["Last backtest", strategy.last_backtest ? `${humanize(strategy.last_backtest.status)} · ${formatTime(strategy.last_backtest.created_at)}` : "None yet"],
                ]} />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title={`Parameters · v${latest.version}`} description={latest.notes || undefined} />
              <CardBody>
                <KeyValue items={Object.entries(latest.parameters).map(([k, v]) => [k.replaceAll("_", " "), <span key={k} className="num">{String(v)}</span>])} />
              </CardBody>
            </Card>
          </div>
        </div>
      )}
      {strategy && assigning && <AssignDialog strategy={strategy} open onClose={() => setAssigning(false)} onDone={() => { setAssigning(false); void list.reload(); }} />}
      {strategy && versioning && <VersionDialog strategy={strategy} open onClose={() => setVersioning(false)} onDone={() => { setVersioning(false); void list.reload(); }} />}
    </>
  );
}
