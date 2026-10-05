"use client";

import { FlaskConical, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Segmented, Select, TextInput } from "@/components/ui/Fields";
import { EmptyState, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { Term } from "@/components/ui/Term";
import { api } from "@/lib/api";
import { formatDate, formatPct, formatTime } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Backtest, Dataset, Strategy } from "@/lib/types";

type Mode = "single" | "split" | "walk_forward";

export function BacktestingScreen() {
  const { isOwner } = useSession();
  const runs = useApi<Backtest[]>("/backtests", undefined, 4000);
  return (
    <div className="space-y-6">
      <PageHeader title="Backtesting" description="Run a strategy on historical data with the same strategy and risk code as live trading. Fills happen at the next bar's open — the strategy never sees the future." />
      {isOwner && <NewBacktest onCreated={() => void runs.reload()} />}
      <Card>
        <CardHeader title="Runs" description="Historical results never guarantee future performance." />
        <DataTable
          caption="Backtest runs"
          rows={runs.data}
          loading={runs.loading}
          error={runs.error}
          rowKey={(r) => r.id}
          empty={<EmptyState icon={FlaskConical} title="No backtests yet">Choose data and press “Run backtest”.</EmptyState>}
          columns={[
            { key: "name", header: "Run", cell: (r) => <Link href={`/backtesting/${r.id}`} className="font-medium text-fg hover:text-accent">{r.name}</Link> },
            { key: "kind", header: "Type", hideBelow: "md", cell: (r) => <span className="text-fg-muted">{KIND[r.kind] ?? r.kind}</span> },
            { key: "data", header: "Data", hideBelow: "lg", cell: (r) => <span className="text-fg-muted">{r.symbol} {r.timeframe} · {r.data_source === "synthetic" ? <Badge tone="warning">SYNTHETIC</Badge> : r.data_source}</span> },
            { key: "period", header: "Period", hideBelow: "lg", cell: (r) => <span className="text-xs text-fg-subtle">{formatDate(r.start)} – {formatDate(r.end)}</span> },
            { key: "status", header: "Status", cell: (r) => r.status === "RUNNING" ? <Badge tone="info">Running {r.progress}%</Badge> : <Badge tone={r.status === "COMPLETED" ? "positive" : r.status === "FAILED" ? "negative" : "neutral"}>{r.status.toLowerCase()}</Badge> },
            { key: "return", header: "Return", align: "right", cell: (r) => (r.metrics ? formatPct(r.metrics.return_pct, 2, true) : "—") },
            { key: "trades", header: "Trades", align: "right", hideBelow: "sm", cell: (r) => r.metrics?.trades ?? "—" },
            { key: "created", header: "Created", hideBelow: "md", cell: (r) => <span className="text-xs text-fg-subtle">{formatTime(r.created_at)}</span> },
          ]}
        />
      </Card>
    </div>
  );
}

const KIND: Record<string, string> = { SINGLE: "Single run", SPLIT: "In-sample / out-of-sample", WALK_FORWARD: "Walk-forward", SENSITIVITY: "Sensitivity" };

function NewBacktest({ onCreated }: { onCreated: () => void }) {
  const router = useRouter();
  const strategies = useApi<Strategy[]>("/strategies");
  const datasets = useApi<Dataset[]>("/datasets");
  const [versionId, setVersionId] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [capital, setCapital] = useState("10000");
  const [risk, setRisk] = useState("0.5");
  const [spread, setSpread] = useState("1.2");
  const [commission, setCommission] = useState("3.5");
  const [slippage, setSlippage] = useState("0.2");
  const [mode, setMode] = useState<Mode>("single");
  const [dataOpen, setDataOpen] = useState(false);
  const action = useAction();

  const versions = useMemo(() => (strategies.data ?? []).flatMap((s) => s.versions.map((v) => ({ ...v, name: s.name }))), [strategies.data]);
  const dataset = datasets.data?.find((d) => d.id === datasetId);
  const pickDataset = (id: string) => {
    setDatasetId(id);
    const d = datasets.data?.find((x) => x.id === id);
    if (d?.first_bar && d.last_bar) {
      setStart(new Date(new Date(d.first_bar).getTime() + 30 * 86400000).toISOString().slice(0, 10));
      setEnd(d.last_bar.slice(0, 10));
    }
  };
  const run = async () => {
    const created = await action.run(() => api<Backtest>("/backtests", { method: "POST", body: {
      mode, strategy_version_id: versionId || versions[versions.length - 1]?.id, dataset_id: datasetId, start, end, initial_capital: capital,
      risk: { risk_per_trade_pct: risk, allowed_sessions: ["ASIA", "LONDON", "OVERLAP", "NEW_YORK"], max_data_age_seconds: 120 },
      costs: { spread_pips: spread, commission_per_lot: commission, slippage_pips: slippage },
      train_months: 3, test_months: 1,
    } }));
    if (created) {
      onCreated();
      router.push(`/backtesting/${created.id}`);
    }
  };

  return (
    <Card>
      <CardHeader title="New backtest" action={<Button size="sm" variant="ghost" onClick={() => setDataOpen(true)}><Upload className="size-3.5" aria-hidden /> Manage data</Button>} />
      <CardBody className="space-y-5">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Strategy">
            <Select value={versionId} onChange={(e) => setVersionId(e.target.value)}>
              {versions.length === 0 && <option value="">No strategies yet (start the engine)</option>}
              {[...versions].reverse().map((v) => <option key={v.id} value={v.id}>{v.name} v{v.version}</option>)}
            </Select>
          </Field>
          <Field label="Symbol & data" hint={dataset?.source === "synthetic" ? "SYNTHETIC data — useful for testing the system, says nothing about real markets." : undefined}>
            <Select value={datasetId} onChange={(e) => pickDataset(e.target.value)}>
              <option value="">{datasets.data?.length ? "Choose a dataset…" : "No data yet — use “Manage data”"}</option>
              {datasets.data?.map((d) => <option key={d.id} value={d.id}>{d.symbol} {d.timeframe} · {d.source.toUpperCase()} · {d.bar_count.toLocaleString()} bars</option>)}
            </Select>
          </Field>
          <Field label="Validation">
            <Segmented size="sm" label="Validation" value={mode} onChange={setMode}
              options={[{ value: "single", label: "Single" }, { value: "split", label: "In/out-of-sample" }, { value: "walk_forward", label: "Walk-forward" }]} />
          </Field>
          <Field label="From"><TextInput type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="To"><TextInput type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
          <Field label="Initial balance (USD)"><TextInput inputMode="decimal" value={capital} onChange={(e) => setCapital(e.target.value)} className="num" /></Field>
          <Field label="Risk per trade (%)"><TextInput inputMode="decimal" value={risk} onChange={(e) => setRisk(e.target.value)} className="num" /></Field>
          <Field label={<><Term id="spread" /> (pips)</>}><TextInput inputMode="decimal" value={spread} onChange={(e) => setSpread(e.target.value)} className="num" /></Field>
          <Field label="Commission (per lot, round turn)"><TextInput inputMode="decimal" value={commission} onChange={(e) => setCommission(e.target.value)} className="num" /></Field>
          <Field label="Slippage (pips)"><TextInput inputMode="decimal" value={slippage} onChange={(e) => setSlippage(e.target.value)} className="num" /></Field>
        </div>
        {mode === "walk_forward" && <p className="text-xs text-fg-subtle">Walk-forward uses 3-month training and 1-month test windows; parameters are chosen on each training window only, then tested on the unseen month that follows.</p>}
        {action.error && <Notice tone="danger" title="Could not start the backtest">{action.error}</Notice>}
        <div className="flex justify-end border-t border-line pt-4">
          <Button variant="primary" onClick={() => void run()} disabled={action.busy || !datasetId || !start || !end}>{action.busy ? "Starting…" : "Run backtest"}</Button>
        </div>
      </CardBody>
      <DataDialog open={dataOpen} onClose={() => setDataOpen(false)} onChange={() => void datasets.reload()} datasets={datasets.data ?? []} />
    </Card>
  );
}

function DataDialog({ open, onClose, onChange, datasets }: { open: boolean; onClose: () => void; onChange: () => void; datasets: Dataset[] }) {
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("H1");
  const [days, setDays] = useState("365");
  const [file, setFile] = useState<File | null>(null);
  const action = useAction();
  const synth = async () => {
    const ok = await action.run(() => api("/datasets/synthetic", { method: "POST", body: { symbol, timeframe, days: Number(days) } }));
    if (ok !== null) onChange();
  };
  const upload = async () => {
    if (!file) return;
    const form = new FormData();
    form.set("file", file);
    form.set("symbol", symbol);
    form.set("timeframe", timeframe);
    const ok = await action.run(() => api("/datasets/import", { method: "POST", body: form }));
    if (ok !== null) { setFile(null); onChange(); }
  };
  const remove = async (id: string) => {
    const ok = await action.run(() => api(`/datasets/${id}`, { method: "DELETE" }));
    if (ok !== null) onChange();
  };
  return (
    <Dialog open={open} onClose={onClose} size="lg" title="Historical data">
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Symbol"><TextInput value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} /></Field>
          <Field label="Timeframe"><Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>{["M15", "M30", "H1", "H4", "D1"].map((t) => <option key={t}>{t}</option>)}</Select></Field>
          <Field label="Days (synthetic)"><TextInput value={days} onChange={(e) => setDays(e.target.value)} className="num" /></Field>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => void synth()} disabled={action.busy}>Generate SYNTHETIC data</Button>
          <label className="inline-flex items-center gap-2 text-sm text-fg-muted">
            <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
          </label>
          <Button onClick={() => void upload()} disabled={!file || action.busy}>Import CSV</Button>
        </div>
        <p className="text-xs text-fg-subtle">CSV: MetaTrader exports or generic time,open,high,low,close[,volume] files. Synthetic data is labelled everywhere and is only for testing the system.</p>
        {action.error && <Notice tone="danger">{action.error}</Notice>}
        <ul className="divide-y divide-line rounded-lg border border-line">
          {datasets.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span><span className="font-medium">{d.symbol} {d.timeframe}</span> <span className="text-fg-subtle">· {d.source} · {d.bar_count.toLocaleString()} bars · {formatDate(d.first_bar)} – {formatDate(d.last_bar)}</span></span>
              <Button size="sm" variant="ghost" onClick={() => void remove(d.id)}>Delete</Button>
            </li>
          ))}
          {datasets.length === 0 && <li className="px-3 py-4 text-sm text-fg-subtle">No datasets yet.</li>}
        </ul>
      </div>
    </Dialog>
  );
}
