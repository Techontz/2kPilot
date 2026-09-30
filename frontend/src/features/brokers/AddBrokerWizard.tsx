"use client";

import { Check, Cpu, MonitorSmartphone } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Select, TextInput, Toggle } from "@/components/ui/Fields";
import { EnvBadge, KeyValue, Notice } from "@/components/ui/Misc";
import { Term } from "@/components/ui/Term";
import { apiRequest } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatMoney } from "@/lib/format";
import type { AccountEnvironment, Connector, Dataset, RiskProfile, TradingAccount } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApiResource } from "@/lib/useApiResource";

const STEPS = ["Type", "Demo / Live", "Details", "Test", "Verify", "Risk profile", "Save"] as const;

interface TestResult {
  account: {
    account_id: string;
    name: string;
    server: string;
    currency: string;
    environment: AccountEnvironment;
    balance: string | null;
    equity: string | null;
    leverage: number | null;
    trade_allowed: boolean;
  };
  symbol_count: number;
  warnings: string[];
}

function Stepper({ step }: { step: number }) {
  return (
    <ol className="mb-6 flex flex-wrap gap-x-4 gap-y-2" aria-label="Progress">
      {STEPS.map((name, i) => (
        <li key={name} className="flex items-center gap-1.5 text-xs" aria-current={i === step ? "step" : undefined}>
          <span
            className={cn(
              "flex size-5 items-center justify-center rounded-full border text-[10px] font-semibold",
              i < step && "border-positive/50 bg-positive-soft text-positive",
              i === step && "border-accent bg-accent text-canvas",
              i > step && "border-line-strong text-fg-subtle",
            )}
          >
            {i < step ? <Check className="size-3" aria-hidden /> : i + 1}
          </span>
          <span className={i === step ? "text-fg" : "text-fg-subtle"}>{name}</span>
        </li>
      ))}
    </ol>
  );
}

export function AddBrokerWizard({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: (a: TradingAccount) => void }) {
  const connectors = useApiResource<Connector[]>("/brokers/connectors", { enabled: open, refetchOnFocus: false });
  const profiles = useApiResource<RiskProfile[]>("/risk/profiles", { enabled: open, refetchOnFocus: false });
  const datasets = useApiResource<Dataset[]>("/market/datasets", { enabled: open, refetchOnFocus: false });
  const [step, setStep] = useState(0);
  const [type, setType] = useState<Connector["id"] | null>(null);
  const [env, setEnv] = useState<AccountEnvironment | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [label, setLabel] = useState("");
  const [replay, setReplay] = useState<Record<string, string>>({});
  const [ackLive, setAckLive] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [profileId, setProfileId] = useState<string>("");
  const test = useAction();
  const save = useAction();

  const connector = connectors.data?.find((c) => c.id === type) ?? null;
  const fields = useMemo(() => connector?.fields.filter((f) => f.name !== "dataset_symbol_map") ?? [], [connector]);

  const reset = () => {
    setStep(0);
    setType(null);
    setEnv(null);
    setValues({});
    setLabel("");
    setReplay({});
    setAckLive(false);
    setResult(null);
    setConfirmed(false);
    setProfileId("");
    test.setError(null);
    save.setError(null);
  };
  const close = () => {
    reset();
    onClose();
  };

  const payload = () => {
    const settings: Record<string, unknown> = {};
    const credentials: Record<string, string> = {};
    for (const f of connector?.fields ?? []) {
      const v = values[f.name] ?? f.default ?? "";
      if (f.secret) credentials[f.name] = v;
      else if (f.name !== "dataset_symbol_map") settings[f.name] = v;
    }
    if (type === "paper" && values.price_source === "replay") {
      settings.dataset_symbol_map = replay;
      settings.symbols = Object.keys(replay).join(",");
    }
    return { connector_type: type, expected_environment: env, settings, credentials, label };
  };

  const runTest = async () => {
    setResult(null);
    const res = await test.run(() => apiRequest<TestResult>("/brokers/connections/test", { method: "POST", body: payload() }));
    if (res) {
      setResult(res);
      setStep(4);
    }
  };

  const runSave = async () => {
    const account = await save.run(() =>
      apiRequest<TradingAccount>("/brokers/connections", {
        method: "POST",
        body: { ...payload(), risk_profile_id: profileId || null, acknowledge_live: ackLive },
      }),
    );
    if (account) {
      onSaved(account);
      reset();
    }
  };

  const defaultProfile = profiles.data?.[0]?.id ?? "";
  const requiredMissing = fields.some((f) => f.required && !(values[f.name] ?? f.default ?? "").toString().trim());
  const replayMode = type === "paper" && (values.price_source ?? "synthetic") === "replay";

  const next = () => setStep((s) => s + 1);
  const back = () => setStep((s) => Math.max(0, s - 1));

  let body: React.ReactNode = null;
  let footer: React.ReactNode = null;

  if (step === 0) {
    body = (
      <div className="grid gap-3 sm:grid-cols-2">
        {connectors.data?.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              setType(c.id);
              setEnv(c.id === "paper" ? "PAPER" : null);
              setValues({});
            }}
            className={cn(
              "rounded-lg border p-4 text-left transition-colors",
              type === c.id ? "border-accent bg-surface-raised" : "border-line hover:bg-surface-raised",
            )}
          >
            <div className="flex items-center gap-2 text-sm font-semibold">
              {c.id === "paper" ? <Cpu className="size-4 text-fg-muted" aria-hidden /> : <MonitorSmartphone className="size-4 text-fg-muted" aria-hidden />}
              {c.name}
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-fg-muted">{c.status_detail}</p>
          </button>
        ))}
      </div>
    );
    footer = <Button variant="primary" disabled={!type} onClick={() => setStep(type === "paper" ? 2 : 1)}>Continue</Button>;
  } else if (step === 1) {
    body = (
      <div className="space-y-4">
        <p className="text-sm text-fg-muted">
          Which kind of MetaTrader 5 account is this? 2kFX will verify it with the broker and refuse to save it if
          the broker reports something different.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {(["DEMO", "LIVE"] as const).map((e) => (
            <button
              key={e}
              type="button"
              onClick={() => setEnv(e)}
              className={cn(
                "rounded-lg border p-4 text-left",
                env === e ? (e === "LIVE" ? "border-live bg-live-soft" : "border-accent bg-surface-raised") : "border-line hover:bg-surface-raised",
              )}
            >
              <EnvBadge env={e} />
              <p className="mt-2 text-xs text-fg-muted">
                {e === "DEMO" ? <><Term id="demoAccount">Demo</Term>: virtual money. Recommended while learning.</> : <><Term id="liveAccount">Live</Term>: REAL money. It will be saved for monitoring only — it can never trade while the server&apos;s LIVE lock is on.</>}
              </p>
            </button>
          ))}
        </div>
        {env === "LIVE" && (
          <Notice tone="danger" title="Real-money account">
            <Toggle checked={ackLive} onChange={setAckLive} label="I understand this account holds real money and must not trade until the live-readiness review is complete." />
          </Notice>
        )}
      </div>
    );
    footer = (
      <>
        <Button variant="ghost" onClick={back}>Back</Button>
        <Button variant="primary" disabled={!env || (env === "LIVE" && !ackLive)} onClick={next}>Continue</Button>
      </>
    );
  } else if (step === 2 && connector) {
    body = (
      <div className="space-y-4">
        <Field label="Name for this account" hint="Shown across the dashboard.">
          <TextInput value={label} maxLength={120} placeholder={type === "paper" ? "Paper account" : "My MT5 demo"} onChange={(e) => setLabel(e.target.value)} />
        </Field>
        {fields.map((f) => {
          const value = values[f.name] ?? f.default ?? "";
          const set = (v: string) => setValues((prev) => ({ ...prev, [f.name]: v }));
          if (f.name === "symbols" && replayMode) return null;
          if (f.kind === "select") {
            return (
              <Field key={f.name} label={f.label} hint={f.help}>
                <Select value={value} onChange={(e) => set(e.target.value)}>
                  {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </Select>
              </Field>
            );
          }
          if (f.kind === "boolean") {
            return <Toggle key={f.name} checked={value !== "false"} onChange={(v) => set(String(v))} label={f.label} description={f.help} />;
          }
          return (
            <Field key={f.name} label={<>{f.label}{f.secret && <span className="ml-1 text-fg-subtle">(encrypted, never shown again)</span>}</>} hint={f.help}>
              <TextInput
                type={f.secret ? "password" : f.kind === "number" ? "number" : "text"}
                autoComplete={f.secret ? "new-password" : "off"}
                value={value}
                onChange={(e) => set(e.target.value)}
              />
            </Field>
          );
        })}
        {replayMode && (
          <Field label="Datasets to replay" hint="One dataset per symbol, all with the same timeframe.">
            <div className="space-y-1.5 rounded-lg border border-line p-3">
              {datasets.data?.length === 0 && <p className="text-xs text-fg-subtle">No datasets yet — import or generate one on the Markets page.</p>}
              {datasets.data?.map((d) => (
                <Toggle
                  key={d.id}
                  checked={replay[d.symbol] === d.id}
                  onChange={(on) =>
                    setReplay((prev) => {
                      const nextMap = { ...prev };
                      if (on) nextMap[d.symbol] = d.id;
                      else delete nextMap[d.symbol];
                      return nextMap;
                    })
                  }
                  label={`${d.symbol} ${d.timeframe} · ${d.source.toUpperCase()}`}
                  description={`${d.bar_count.toLocaleString()} bars`}
                />
              ))}
            </div>
          </Field>
        )}
        {type === "mt5_bridge" && (
          <Notice tone="info" title="Needs the 2kFX MT5 Bridge">
            MetaTrader 5 only runs on Windows. Install the bridge next to your MT5 terminal first (see docs/MT5_BRIDGE_SETUP.md).
          </Notice>
        )}
      </div>
    );
    footer = (
      <>
        <Button variant="ghost" onClick={() => setStep(type === "paper" ? 0 : 1)}>Back</Button>
        <Button variant="primary" disabled={requiredMissing || (replayMode && !Object.keys(replay).length)} onClick={next}>Continue</Button>
      </>
    );
  } else if (step === 3) {
    body = (
      <div className="space-y-4">
        <p className="text-sm text-fg-muted">
          2kFX will now connect, log in, read the account, and check with the broker whether it really is a{" "}
          <strong className="text-fg">{env}</strong> account. Nothing is saved in this step.
        </p>
        {test.error && <Notice tone="danger" title="Connection test failed">{test.error}</Notice>}
      </div>
    );
    footer = (
      <>
        <Button variant="ghost" onClick={back}>Back</Button>
        <Button variant="primary" disabled={test.busy} onClick={() => void runTest()}>{test.busy ? "Testing…" : "Test connection"}</Button>
      </>
    );
  } else if (step === 4 && result) {
    const a = result.account;
    body = (
      <div className="space-y-4">
        <Notice tone="success" title="Connected and verified">
          The broker confirms this is a {a.environment} account. {result.symbol_count} symbols are available.
        </Notice>
        {result.warnings.map((w) => <Notice key={w} tone="warning">{w}</Notice>)}
        <KeyValue
          items={[
            ["Account", a.account_id],
            ["Name", a.name || "—"],
            ["Server", a.server],
            ["Type", <EnvBadge key="e" env={a.environment} />],
            [<Term key="b" id="balance" />, formatMoney(a.balance, a.currency)],
            [<Term key="q" id="equity" />, formatMoney(a.equity, a.currency)],
            ["Leverage", a.leverage ? `1:${a.leverage}` : "—"],
          ]}
        />
        <Toggle checked={confirmed} onChange={setConfirmed} label="Yes, this is the account I want to connect." />
      </div>
    );
    footer = (
      <>
        <Button variant="ghost" onClick={() => setStep(2)}>Back</Button>
        <Button variant="primary" disabled={!confirmed} onClick={() => { setProfileId(profileId || defaultProfile); next(); }}>Continue</Button>
      </>
    );
  } else if (step === 5) {
    const chosen = profiles.data?.find((p) => p.id === profileId);
    body = (
      <div className="space-y-4">
        <p className="text-sm text-fg-muted">
          The risk profile sets the limits the risk engine enforces on this account. You can change it any time on the
          Risk Management page.
        </p>
        <Field label="Risk profile">
          <Select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
            <option value="">No profile (account cannot trade)</option>
            {profiles.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        {chosen && (
          <KeyValue
            items={[
              ["Risk per trade", `${chosen.limits.risk_per_trade_pct}% of equity`],
              ["Daily loss limit", chosen.limits.max_daily_loss_pct ? `${chosen.limits.max_daily_loss_pct}%` : "none"],
              ["Max drawdown", chosen.limits.max_drawdown_pct ? `${chosen.limits.max_drawdown_pct}%` : "none"],
              ["Max open positions", String(chosen.limits.max_open_positions ?? "none")],
            ]}
          />
        )}
      </div>
    );
    footer = (
      <>
        <Button variant="ghost" onClick={back}>Back</Button>
        <Button variant="primary" onClick={next}>Continue</Button>
      </>
    );
  } else if (step === 6) {
    body = (
      <div className="space-y-4">
        <KeyValue
          items={[
            ["Connection", connector?.name ?? "—"],
            ["Account", `${label || result?.account.account_id} (${env})`],
            ["Risk profile", profiles.data?.find((p) => p.id === profileId)?.name ?? "None"],
            ["Trading", "Disabled until you enable it"],
          ]}
        />
        <Notice tone="info">
          The connection is tested again when you save. Secrets are encrypted before they are stored and are never
          displayed again.
        </Notice>
        {save.error && <Notice tone="danger" title="Could not save">{save.error}</Notice>}
      </div>
    );
    footer = (
      <>
        <Button variant="ghost" onClick={back}>Back</Button>
        <Button variant="primary" disabled={save.busy} onClick={() => void runSave()}>{save.busy ? "Saving…" : "Save account"}</Button>
      </>
    );
  }

  return (
    <Dialog open={open} onClose={close} title="Add broker / trading account" size="lg" footer={footer}>
      <Stepper step={step} />
      {body}
    </Dialog>
  );
}
