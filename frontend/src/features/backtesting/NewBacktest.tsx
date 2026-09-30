"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Segmented, Select, TextInput } from "@/components/ui/Fields";
import { Notice } from "@/components/ui/Misc";
import { Term } from "@/components/ui/Term";
import { apiRequest } from "@/lib/api";
import type { BacktestDetail, Dataset, RiskProfile, StrategyInfo } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApiResource } from "@/lib/useApiResource";

type Mode = "single" | "split" | "walk_forward" | "sensitivity";

const MODE_HELP: Record<Mode, string> = {
  single: "One run over the whole period.",
  split: "Run on the first part (in-sample), then check the untouched rest (out-of-sample). The honest way to test an idea.",
  walk_forward: "Repeatedly pick the best parameters on a training window, then test them on the following unseen window.",
  sensitivity: "Run a small grid of parameter values. Results that collapse when a parameter changes slightly are a warning sign.",
};

function dateInput(iso: string | null | undefined) {
  return iso ? iso.slice(0, 10) : "";
}

export function NewBacktest({ open, onClose, onCreated, presetVersion }: { open: boolean; onClose: () => void; onCreated: (b: BacktestDetail) => void; presetVersion: string | null }) {
  const strategies = useApiResource<StrategyInfo[]>("/strategies", { enabled: open, refetchOnFocus: false });
  const datasets = useApiResource<Dataset[]>("/market/datasets", { enabled: open, refetchOnFocus: false });
  const profiles = useApiResource<RiskProfile[]>("/risk/profiles", { enabled: open, refetchOnFocus: false });
  const versions = useMemo(() => (strategies.data ?? []).flatMap((s) => s.versions.map((v) => ({ ...v, strategy: s }))), [strategies.data]);
  const [version, setVersion] = useState("");
  const [dataset, setDataset] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [capital, setCapital] = useState("10000");
  const [profile, setProfile] = useState("");
  const [riskPct, setRiskPct] = useState("");
  const [spread, setSpread] = useState("");
  const [commission, setCommission] = useState("3.5");
  const [slippage, setSlippage] = useState("0.2");
  const [mode, setMode] = useState<Mode>("single");
  const [split, setSplit] = useState("0.7");
  const [train, setTrain] = useState("6");
  const [test, setTest] = useState("2");
  const [gridParam, setGridParam] = useState("reward_risk");
  const [gridValues, setGridValues] = useState("1.5, 2, 2.5, 3");
  const action = useAction();

  // Defaults are derived during render; user choices override them.
  const versionId = version || (presetVersion && versions.some((v) => v.id === presetVersion) ? presetVersion : versions.at(-1)?.id) || "";
  const profileId = profile || profiles.data?.[0]?.id || "";
  const datasetId = dataset || datasets.data?.[0]?.id || "";
  const ds = datasets.data?.find((d) => d.id === datasetId);
  const defaultStart = (() => {
    if (!ds?.first_bar) return "";
    const first = new Date(ds.first_bar);
    first.setDate(first.getDate() + 90); // leave warm-up history for indicators
    return first.toISOString().slice(0, 10);
  })();
  const startValue = start || defaultStart;
  const endValue = end || dateInput(ds?.last_bar);

  const selectedVersion = versions.find((v) => v.id === versionId);
  const numericParams = selectedVersion
    ? Object.entries(selectedVersion.strategy.parameter_schema.properties).filter(([, p]) => p.type === "integer" || p.type === "number").map(([k]) => k)
    : [];

  const submit = async () => {
    const limits = { ...(profiles.data?.find((p) => p.id === profileId)?.limits ?? {}) };
    if (riskPct) limits.risk_per_trade_pct = riskPct;
    const grid = mode === "sensitivity" || mode === "walk_forward"
      ? { [gridParam]: gridValues.split(",").map((v) => v.trim()).filter(Boolean).map(Number) }
      : {};
    const res = await action.run(() =>
      apiRequest<BacktestDetail>("/backtests", {
        method: "POST",
        body: {
          mode, strategy_version_id: versionId, dataset_id: datasetId,
          start: `${startValue}T00:00:00Z`, end: `${endValue}T23:59:59Z`, initial_capital: capital,
          risk: limits, costs: { spread_pips: spread || null, commission_per_lot: commission, slippage_pips: slippage },
          split_ratio: Number(split), train_months: Number(train), test_months: Number(test), grid,
        },
      }),
    );
    if (res) onCreated(res);
  };

  return (
    <Dialog open={open} onClose={onClose} size="xl" title="New backtest"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={action.busy || !versionId || !datasetId || !startValue || !endValue} onClick={() => void submit()}>{action.busy ? "Starting…" : "Run backtest"}</Button></>}>
      <div className="space-y-6">
        {datasets.data?.length === 0 && (
          <Notice tone="warning" title="No historical data yet">Import a CSV, download from MT5 or generate synthetic data on the Markets page first.</Notice>
        )}
        <section className="grid gap-4 sm:grid-cols-2">
          <Field label="Strategy version">
            <Select value={versionId} onChange={(e) => setVersion(e.target.value)}>
              {versions.map((v) => <option key={v.id} value={v.id}>{v.strategy.name} v{v.version}{v.notes ? ` — ${v.notes}` : ""}</option>)}
            </Select>
          </Field>
          <Field label="Historical data" hint={ds ? `${ds.bar_count.toLocaleString()} ${ds.timeframe} bars · ${ds.source.toUpperCase()}` : undefined}>
            <Select value={datasetId} onChange={(e) => { setDataset(e.target.value); setStart(""); setEnd(""); }}>
              {datasets.data?.map((d) => <option key={d.id} value={d.id}>{d.symbol} {d.timeframe} · {d.source === "synthetic" ? "SYNTHETIC" : d.source.toUpperCase()}</option>)}
            </Select>
          </Field>
          <Field label="From" hint="Earlier bars are used as indicator warm-up."><TextInput type="date" value={startValue} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="To"><TextInput type="date" value={endValue} onChange={(e) => setEnd(e.target.value)} /></Field>
          <Field label="Starting capital (USD)"><TextInput inputMode="decimal" value={capital} onChange={(e) => setCapital(e.target.value)} /></Field>
          <Field label="Risk profile" hint="Every live risk rule is applied in the simulation.">
            <Select value={profileId} onChange={(e) => setProfile(e.target.value)}>
              {profiles.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </Field>
          <Field label="Risk per trade override (%)" hint="Optional."><TextInput inputMode="decimal" value={riskPct} placeholder="from profile" onChange={(e) => setRiskPct(e.target.value)} /></Field>
        </section>
        <section>
          <p className="mb-3 text-xs font-medium tracking-wide text-fg-subtle uppercase">Trading costs</p>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={<><Term id="spread" /> (pips)</>} hint="Empty = use each bar's recorded spread."><TextInput inputMode="decimal" value={spread} placeholder="from data" onChange={(e) => setSpread(e.target.value)} /></Field>
            <Field label="Commission per lot per side (USD)"><TextInput inputMode="decimal" value={commission} onChange={(e) => setCommission(e.target.value)} /></Field>
            <Field label="Slippage (pips)" hint="Applied to market entries and stop exits."><TextInput inputMode="decimal" value={slippage} onChange={(e) => setSlippage(e.target.value)} /></Field>
          </div>
        </section>
        <section className="space-y-3">
          <p className="text-xs font-medium tracking-wide text-fg-subtle uppercase">Validation</p>
          <Segmented label="Mode" value={mode} onChange={setMode} options={[
            { value: "single", label: "Single" }, { value: "split", label: "In / out of sample" },
            { value: "walk_forward", label: "Walk-forward" }, { value: "sensitivity", label: "Sensitivity" },
          ]} />
          <p className="text-sm text-fg-muted">{MODE_HELP[mode]}</p>
          {mode === "split" && <Field label="In-sample share" hint="0.7 = first 70% in-sample, last 30% out-of-sample."><TextInput inputMode="decimal" value={split} onChange={(e) => setSplit(e.target.value)} /></Field>}
          {mode === "walk_forward" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Training window (months)"><TextInput inputMode="numeric" value={train} onChange={(e) => setTrain(e.target.value)} /></Field>
              <Field label="Test window (months)"><TextInput inputMode="numeric" value={test} onChange={(e) => setTest(e.target.value)} /></Field>
            </div>
          )}
          {(mode === "sensitivity" || mode === "walk_forward") && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Parameter to vary">
                <Select value={gridParam} onChange={(e) => setGridParam(e.target.value)}>
                  {numericParams.map((p) => <option key={p} value={p}>{p}</option>)}
                </Select>
              </Field>
              <Field label="Values (comma separated)" hint="Up to 16 runs."><TextInput value={gridValues} onChange={(e) => setGridValues(e.target.value)} /></Field>
            </div>
          )}
        </section>
        {action.error && <Notice tone="danger">{action.error}</Notice>}
      </div>
    </Dialog>
  );
}
