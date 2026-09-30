"use client";

import { Database, Download, Sparkles, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Select, TextInput } from "@/components/ui/Fields";
import { EmptyState, Notice } from "@/components/ui/Misc";
import { apiRequest } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Dataset, Timeframe, TradingAccount } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApiResource } from "@/lib/useApiResource";

const TIMEFRAMES: Timeframe[] = ["M15", "M30", "H1", "H4", "D1"];
const SYNTHETIC = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD"];
type Mode = "import" | "synthetic" | "download" | null;

export function Datasets({ accounts }: { accounts: TradingAccount[] }) {
  const { isOwner } = useSession();
  const list = useApiResource<Dataset[]>("/market/datasets");
  const [mode, setMode] = useState<Mode>(null);
  const [symbol, setSymbol] = useState("EURUSD");
  const [tf, setTf] = useState<Timeframe>("H1");
  const [offset, setOffset] = useState("0");
  const [file, setFile] = useState<File | null>(null);
  const [days, setDays] = useState("730");
  const [seed, setSeed] = useState("42");
  const [account, setAccount] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [report, setReport] = useState<string | null>(null);
  const action = useAction();
  const mt5 = accounts.filter((a) => a.connector_type !== "paper" && a.environment !== "PAPER");

  const close = () => {
    setMode(null);
    action.setError(null);
  };
  const submit = async () => {
    setReport(null);
    if (mode === "import" && file) {
      const content = await file.text();
      const res = await action.run(() => apiRequest<{ report: { imported: number; dropped_count: number; validation: { gaps: number } } }>("/market/datasets/import", {
        method: "POST", body: { symbol, timeframe: tf, utc_offset_hours: Number(offset), filename: file.name, content },
      }));
      if (res) setReport(`Imported ${res.report.imported.toLocaleString()} bars; ${res.report.dropped_count} rows dropped; ${res.report.validation.gaps} gaps.`);
      else return;
    } else if (mode === "synthetic") {
      if (!(await action.run(() => apiRequest("/market/datasets/synthetic", { method: "POST", body: { symbol, timeframe: tf, days: Number(days), seed: Number(seed) } })))) return;
    } else if (mode === "download") {
      if (!(await action.run(() => apiRequest("/market/datasets/download", { method: "POST", body: { account_id: account, symbol, timeframe: tf, start: `${from}T00:00:00Z`, end: `${to}T00:00:00Z` } })))) return;
    }
    close();
    void list.reload();
  };

  return (
    <Card>
      <CardHeader
        title="Historical data"
        description="Candles used for backtesting and replay. Validation reports gaps and bad bars."
        action={isOwner && (
          <div className="flex flex-wrap justify-end gap-2">
            <Button size="sm" onClick={() => setMode("import")}><Upload aria-hidden className="size-3.5" />Import CSV</Button>
            <Button size="sm" disabled={!mt5.length} title={mt5.length ? undefined : "Needs a connected MT5 account"} onClick={() => { setAccount(mt5[0]?.id ?? ""); setMode("download"); }}><Download aria-hidden className="size-3.5" />From MT5</Button>
            <Button size="sm" onClick={() => setMode("synthetic")}><Sparkles aria-hidden className="size-3.5" />Synthetic</Button>
          </div>
        )}
      />
      {report && <Notice tone="success" className="mx-5 mt-4">{report}</Notice>}
      {list.data?.length === 0 ? (
        <EmptyState icon={Database} title="No historical data yet">
          Export bars from MetaTrader 5 (History Center → Export) and import the CSV, download directly from a connected MT5 account, or
          generate clearly-labelled synthetic data to learn the tools.
        </EmptyState>
      ) : (
        <DataTable rows={list.data} loading={list.loading} rowKey={(d) => d.id} columns={[
          { key: "s", header: "Dataset", cell: (d) => <span className="font-medium">{d.symbol} <span className="text-fg-subtle">{d.timeframe}</span></span> },
          { key: "src", header: "Source", cell: (d) => <Badge tone={d.source === "synthetic" ? "warning" : "neutral"}>{d.source === "synthetic" ? "SYNTHETIC" : d.source.toUpperCase()}</Badge> },
          { key: "r", header: "Range", hideBelow: "md", cell: (d) => <span className="text-xs text-fg-muted">{formatDate(d.first_bar)} – {formatDate(d.last_bar)}</span> },
          { key: "b", header: "Bars", align: "right", cell: (d) => d.bar_count.toLocaleString() },
          { key: "g", header: "Gaps", align: "right", hideBelow: "sm", cell: (d) => (d.gap_count ? <span className="text-warning">{d.gap_count}</span> : "0") },
          ...(isOwner ? [{ key: "x", header: <span className="sr-only">Delete</span>, align: "right" as const, cell: (d: Dataset) => (
            <Button size="sm" variant="ghost" aria-label={`Delete ${d.symbol} ${d.timeframe}`} onClick={() => void apiRequest(`/market/datasets/${d.id}`, { method: "DELETE" }).then(() => list.reload())}><Trash2 aria-hidden className="size-3.5" /></Button>
          ) }] : []),
        ]} />
      )}
      <Dialog open={mode !== null} onClose={close} title={mode === "import" ? "Import CSV" : mode === "download" ? "Download from MT5" : "Generate synthetic data"}
        footer={<><Button variant="ghost" onClick={close}>Cancel</Button><Button variant="primary" disabled={action.busy || (mode === "import" && !file) || (mode === "download" && (!from || !to || !account))} onClick={() => void submit()}>{action.busy ? "Working…" : "Continue"}</Button></>}>
        <div className="space-y-4">
          {mode === "synthetic" && <Notice tone="warning" title="Not real market data">Synthetic prices are generated for practising with the tools. Backtests on them say nothing about real markets and are labelled SYNTHETIC everywhere.</Notice>}
          {mode === "download" && (
            <Field label="Account"><Select value={account} onChange={(e) => setAccount(e.target.value)}>{mt5.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</Select></Field>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Symbol">
              {mode === "synthetic" ? (
                <Select value={symbol} onChange={(e) => setSymbol(e.target.value)}>{SYNTHETIC.map((s) => <option key={s}>{s}</option>)}</Select>
              ) : <TextInput value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />}
            </Field>
            <Field label="Timeframe"><Select value={tf} onChange={(e) => setTf(e.target.value as Timeframe)}>{TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}</Select></Field>
          </div>
          {mode === "import" && (
            <>
              <Field label="CSV file" hint="MT5 export (<DATE> <TIME> <OPEN>…) or time,open,high,low,close[,volume].">
                <input type="file" accept=".csv,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm text-fg-muted file:mr-3 file:rounded-md file:border-0 file:bg-surface-raised file:px-3 file:py-1.5 file:text-fg" />
              </Field>
              <Field label="Timestamps are in UTC +" hint="MT5 exports use your broker's server time (often +2 or +3). Enter that offset so bars convert to UTC.">
                <TextInput inputMode="decimal" value={offset} onChange={(e) => setOffset(e.target.value)} />
              </Field>
            </>
          )}
          {mode === "synthetic" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Days of history"><TextInput inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></Field>
              <Field label="Seed" hint="Same seed = same prices."><TextInput inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} /></Field>
            </div>
          )}
          {mode === "download" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="From"><TextInput type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
              <Field label="To"><TextInput type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
            </div>
          )}
          {action.error && <Notice tone="danger">{action.error}</Notice>}
        </div>
      </Dialog>
    </Card>
  );
}
