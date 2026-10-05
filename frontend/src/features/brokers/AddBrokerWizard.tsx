"use client";

import { ArrowLeft, Check, CircleCheck, ExternalLink, FlaskConical, KeyRound, Landmark, Monitor } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { Field, Select, TextInput, Toggle } from "@/components/ui/Fields";
import { EnvBadge, KeyValue, Loading, Notice } from "@/components/ui/Misc";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatMoney, humanize } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Account, AccountEnvironment, ConnectionTestResult, Connector, ConnectorType, DerivAccount, RiskProfile } from "@/lib/types";

const STEPS = ["Choose broker", "Account type", "Authenticate", "Test connection", "Verify account", "Risk profile", "Finish"] as const;
const ICONS: Record<ConnectorType, typeof Landmark> = { paper: FlaskConical, deriv: Landmark, mt5_bridge: Monitor };
const SAVED = "fx.add-broker";

interface WizardState {
  connector: ConnectorType | null;
  environment: AccountEnvironment | null;
  values: Record<string, string>;
  useOauth: boolean;
  derivAccountId: string;
}

const EMPTY: WizardState = { connector: null, environment: null, values: {}, useOauth: false, derivAccountId: "" };

/**
 * Brokers → Add Broker, in seven plain steps. Nothing is saved until Finish,
 * and Finish tests the connection again: a failed connection never appears
 * as CONNECTED.
 */
export function AddBrokerWizard() {
  const router = useRouter();
  const params = useSearchParams();
  const { reloadAccounts, selectAccount } = useAppData();
  const catalog = useApi<{ connectors: Connector[]; vault_configured: boolean; deriv_signed_in: boolean }>("/brokers/connectors");
  const profiles = useApi<RiskProfile[]>("/risk/profiles");
  // Returning from "Sign in with Deriv" (?deriv=…): restore the wizard and continue.
  const [returned] = useState(() => restoreAfterOauth(params.get("deriv")));
  const [step, setStep] = useState(returned.step);
  const [state, setState] = useState<WizardState>(returned.state);
  const [derivAccounts, setDerivAccounts] = useState<DerivAccount[] | null>(null);
  const [test, setTest] = useState<ConnectionTestResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [riskProfileId, setRiskProfileId] = useState("");
  const [label, setLabel] = useState("");
  const [ackLive, setAckLive] = useState(false);
  const [saved, setSaved] = useState<Account | null>(null);
  const action = useAction();

  const connector = catalog.data?.connectors.find((c) => c.id === state.connector) ?? null;

  const defaultProfileId = profiles.data?.find((p) => p.name.includes("default"))?.id ?? profiles.data?.[0]?.id ?? "";
  const profileId = riskProfileId || defaultProfileId;

  const settingsAndCredentials = () => {
    if (!connector) return { settings: {}, credentials: {} };
    const settings: Record<string, string> = {};
    const credentials: Record<string, string> = {};
    for (const field of connector.fields) {
      const value = state.values[field.name] ?? field.default ?? "";
      if (value === "") continue;
      (field.secret ? credentials : settings)[field.name] = value;
    }
    if (connector.id === "deriv") settings.account_id = state.derivAccountId;
    return { settings, credentials };
  };

  const body = () => ({
    connector_type: state.connector,
    expected_environment: state.environment,
    ...settingsAndCredentials(),
    use_oauth: state.useOauth,
  });

  const goTo = (next: number) => {
    action.reset();
    setStep(next);
  };

  const listDerivAccounts = async () => {
    const result = await action.run(() =>
      api<{ accounts: DerivAccount[] }>("/brokers/deriv/accounts", { method: "POST", body: { token: state.values.token ?? "", use_oauth: state.useOauth } }),
    );
    if (result) setDerivAccounts(result.accounts);
  };

  const runTest = async () => {
    setTest(null);
    const result = await action.run(() => api<ConnectionTestResult>("/brokers/test", { method: "POST", body: body() }));
    if (result) {
      setTest(result);
      setConfirmed(false);
      goTo(4);
    }
  };

  const finish = async () => {
    const result = await action.run(() =>
      api<Account>("/brokers", { method: "POST", body: { ...body(), label, risk_profile_id: profileId || null, acknowledge_live: ackLive } }),
    );
    if (result) {
      setSaved(result);
      window.sessionStorage.removeItem(SAVED);
      await reloadAccounts();
      selectAccount(result.id);
    }
  };

  const startOauth = async () => {
    window.sessionStorage.setItem(SAVED, JSON.stringify({ ...state, values: {} }));
    const result = await action.run(() => api<{ url: string }>("/brokers/deriv/oauth/start", { method: "POST" }));
    if (result) window.location.assign(result.url);
  };

  if (!catalog.data) return <Loading label="Loading brokers…" />;
  if (saved) return <Done account={saved} onAnother={() => { setSaved(null); setState(EMPTY); setTest(null); goTo(0); router.replace("/brokers/new"); }} />;

  return (
    <div className="mx-auto max-w-3xl">
      <Link href="/brokers" className="mb-4 inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg"><ArrowLeft className="size-4" aria-hidden /> Brokers</Link>
      <h1 className="text-xl font-semibold tracking-tight">Add broker</h1>
      <Stepper step={step} />
      {!catalog.data.vault_configured && (
        <Notice tone="danger" title="Credential encryption is not configured" className="mb-4">
          Run <code className="num">php artisan fx:keys</code> in backend/ so broker secrets can be stored encrypted.
        </Notice>
      )}

      <Card>
        <CardBody className="space-y-5 p-6">
          {step === 0 && (
            <Section title="Which broker?" hint="You can add as many accounts as you like. Strategies never know which broker they run on.">
              <div className="grid gap-3 sm:grid-cols-3">
                {catalog.data.connectors.map((c) => {
                  const Icon = ICONS[c.id];
                  const selected = state.connector === c.id;
                  return (
                    <button key={c.id} type="button" disabled={c.status !== "available"} aria-pressed={selected}
                      onClick={() => setState({ ...EMPTY, connector: c.id, environment: c.environments.length === 1 ? c.environments[0]! : null })}
                      className={cn("flex flex-col items-start rounded-xl border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                        selected ? "border-accent bg-accent/5" : "border-line hover:border-line-strong")}>
                      <Icon className={cn("size-5", selected ? "text-accent" : "text-fg-muted")} aria-hidden />
                      <span className="mt-3 text-sm font-semibold text-fg">{c.name}</span>
                      <span className="mt-1 text-xs leading-relaxed text-fg-muted">{c.tagline}</span>
                      {c.status !== "available" && <Badge tone="warning" className="mt-3">Needs setup</Badge>}
                    </button>
                  );
                })}
              </div>
              {connector && <p className="text-sm text-fg-muted">{connector.description}</p>}
              {catalog.data.connectors.filter((c) => c.status_detail).map((c) => (
                <Notice key={c.id} tone="warning" title={`${c.name} needs setup`}>{c.status_detail}</Notice>
              ))}
              <Nav onNext={() => goTo(1)} nextDisabled={!connector} />
            </Section>
          )}

          {step === 1 && connector && (
            <Section title="Demo or Live?" hint="Choose what you expect. The broker's own answer is checked in step 5 — a mismatch is refused.">
              <div className="grid gap-3 sm:grid-cols-2">
                {connector.environments.map((env) => (
                  <button key={env} type="button" aria-pressed={state.environment === env} onClick={() => setState({ ...state, environment: env })}
                    className={cn("rounded-xl border p-4 text-left", state.environment === env ? "border-accent bg-accent/5" : "border-line hover:border-line-strong")}>
                    <EnvBadge env={env} />
                    <p className="mt-2 text-sm text-fg-muted">{ENV_TEXT[env]}</p>
                  </button>
                ))}
              </div>
              {state.environment === "LIVE" && (
                <Notice tone="danger" title="Real money">
                  LIVE accounts can be added for monitoring, but they can never trade while the server lock is on (LIVE_TRADING_ENABLED=false), and only with two-factor authentication.
                  <div className="mt-3"><Toggle checked={ackLive} onChange={setAckLive} label="I understand this account holds real money." /></div>
                </Notice>
              )}
              <Nav onBack={() => goTo(0)} onNext={() => goTo(2)} nextDisabled={!state.environment || (state.environment === "LIVE" && !ackLive)} />
            </Section>
          )}

          {step === 2 && connector && (
            <Section title={connector.id === "paper" ? "Simulation settings" : "Authenticate"} hint={AUTH_HINT[connector.id]}>
              {connector.id === "deriv" && connector.auth_methods.includes("oauth") && (
                <div className="rounded-xl border border-line p-4">
                  <p className="text-sm font-medium text-fg">Sign in with Deriv</p>
                  <p className="mt-1 text-sm text-fg-muted">You log in on deriv.com and come back here. 2kFX never sees your Deriv password, and the token stays on the server.</p>
                  <Button className="mt-3" onClick={() => void startOauth()} disabled={action.busy}><ExternalLink className="size-4" aria-hidden /> Sign in with Deriv</Button>
                  <p className="mt-3 text-xs text-fg-subtle">Deriv sign-in tokens last about an hour. For a robot that runs 24/7, a personal access token (below) is more reliable.</p>
                </div>
              )}
              {connector.id !== "paper" && connector.id === "deriv" && <p className="text-xs font-medium tracking-wide text-fg-subtle uppercase">Personal access token</p>}
              <div className="grid gap-4 sm:grid-cols-2">
                {connector.fields.map((field) => (
                  <Field key={field.name} label={field.label} hint={field.help} className={field.kind === "password" || field.name === "symbols" ? "sm:col-span-2" : undefined}>
                    {field.kind === "select" ? (
                      <Select value={state.values[field.name] ?? field.default ?? ""} onChange={(e) => setState({ ...state, values: { ...state.values, [field.name]: e.target.value } })}>
                        {field.options?.map((o) => <option key={o} value={o}>{humanize(o)}</option>)}
                      </Select>
                    ) : field.kind === "boolean" ? (
                      <Select value={state.values[field.name] ?? field.default ?? "true"} onChange={(e) => setState({ ...state, values: { ...state.values, [field.name]: e.target.value } })}>
                        <option value="true">Yes</option><option value="false">No</option>
                      </Select>
                    ) : (
                      <TextInput type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"} autoComplete={field.secret ? "new-password" : "off"}
                        value={state.values[field.name] ?? (field.secret ? "" : field.default ?? "")} placeholder={field.secret ? "Stored encrypted — never shown again" : undefined}
                        onChange={(e) => setState({ ...state, useOauth: field.name === "token" ? false : state.useOauth, values: { ...state.values, [field.name]: e.target.value } })} />
                    )}
                  </Field>
                ))}
              </div>
              <Nav onBack={() => goTo(1)} onNext={() => goTo(3)} nextDisabled={connector.id === "deriv" && !state.useOauth && !(state.values.token ?? "").trim()} />
            </Section>
          )}

          {step === 3 && connector && (
            <Section title="Test the connection" hint="2kFX asks the broker for this account's details. Nothing is saved yet.">
              {state.useOauth && <Notice tone="success" title="Signed in with Deriv">Your Deriv sign-in is held on the server for this setup.</Notice>}
              {connector.id === "deriv" && (
                <div className="space-y-3">
                  <Button onClick={() => void listDerivAccounts()} disabled={action.busy}>{derivAccounts ? "Refresh accounts" : "Find my Deriv accounts"}</Button>
                  {derivAccounts && (
                    <div role="radiogroup" aria-label="Deriv account" className="space-y-2">
                      {derivAccounts.length === 0 && <p className="text-sm text-fg-muted">This token can&apos;t reach any Deriv Options account.</p>}
                      {derivAccounts.map((d) => {
                        const env = d.account_type === "demo" ? "DEMO" : "LIVE";
                        const matches = env === state.environment;
                        return (
                          <button key={d.account_id} type="button" role="radio" aria-checked={state.derivAccountId === d.account_id} disabled={!matches}
                            onClick={() => setState({ ...state, derivAccountId: d.account_id })}
                            className={cn("flex w-full items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left disabled:opacity-50",
                              state.derivAccountId === d.account_id ? "border-accent bg-accent/5" : "border-line hover:border-line-strong")}>
                            <span>
                              <span className="num block text-sm text-fg">{d.account_id}</span>
                              <span className="block text-xs text-fg-subtle">{matches ? `${d.status} · ${d.currency}` : `You chose ${state.environment} in step 2`}</span>
                            </span>
                            <span className="flex items-center gap-3">
                              <span className="num text-sm text-fg">{formatMoney(d.balance, d.currency)}</span>
                              <EnvBadge env={env} />
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
              {action.error && <Notice tone="danger" title="The connection did not work">{action.error}</Notice>}
              <Nav onBack={() => goTo(2)} onNext={() => void runTest()} nextLabel={action.busy ? "Testing…" : "Test connection"}
                nextDisabled={action.busy || (connector.id === "deriv" && !state.derivAccountId)} />
            </Section>
          )}

          {step === 4 && test && (
            <Section title="Verify the account" hint="These details come straight from the broker. Check them before you continue.">
              <Notice tone="success" title="Connection works">The broker confirmed a {test.account.environment} account.</Notice>
              <KeyValue items={[
                ["Account", <span key="a" className="num">{test.account.account_id}</span>],
                ["Type (reported by the broker)", <EnvBadge key="e" env={test.account.environment} />],
                ["Server", test.account.server || "—"],
                ["Currency", test.account.currency],
                ["Balance", <span key="b" className="num">{formatMoney(test.account.balance, test.account.currency)}</span>],
                ["Equity", <span key="q" className="num">{formatMoney(test.account.equity, test.account.currency)}</span>],
                ["Instruments", `${test.symbol_count} (${Object.entries(test.categories).map(([k, v]) => `${v} ${k}`).join(", ") || "—"})`],
                ["Trading allowed", test.account.trade_allowed ? "Yes" : "No — the broker reports trading is not allowed"],
                ["Order types", test.capabilities.pending_orders === false ? "Market orders only" : "Market and pending orders"],
              ]} />
              {test.capabilities.notes?.map((n) => <p key={n} className="text-xs text-fg-subtle">• {n}</p>)}
              {test.warnings.map((w) => <Notice key={w} tone="warning">{w}</Notice>)}
              <Toggle checked={confirmed} onChange={setConfirmed} label="This is the account I want to add." />
              <Nav onBack={() => goTo(3)} onNext={() => goTo(5)} nextDisabled={!confirmed} />
            </Section>
          )}

          {step === 5 && (
            <Section title="Assign a risk profile" hint="Limits for this account: risk per trade, daily and weekly loss, drawdown, exposure, spread and more. You can change it later.">
              <Field label="Risk profile">
                <Select value={profileId} onChange={(e) => setRiskProfileId(e.target.value)}>
                  {profiles.data?.map((p) => <option key={p.id} value={p.id}>{p.name} — {Number(p.risk_per_trade_pct)}% per trade</option>)}
                </Select>
              </Field>
              <Field label="Name for this account" hint="Shown on the account card and in the account switcher.">
                <TextInput value={label} onChange={(e) => setLabel(e.target.value)} placeholder={connector?.id === "paper" ? "Paper practice" : `${connector?.name} ${test?.account.account_id ?? ""}`} maxLength={120} />
              </Field>
              <Nav onBack={() => goTo(4)} onNext={() => goTo(6)} nextDisabled={!profileId} />
            </Section>
          )}

          {step === 6 && test && (
            <Section title="Finish" hint="2kFX tests the connection one more time, saves the account with trading switched OFF, and connects it.">
              <KeyValue items={[
                ["Broker", connector?.name ?? ""],
                ["Account", <span key="a" className="num">{test.account.account_id}</span>],
                ["Type", <EnvBadge key="e" env={test.account.environment} />],
                ["Risk profile", profiles.data?.find((p) => p.id === profileId)?.name ?? "—"],
                ["Trading", "Off until you switch it on"],
              ]} />
              {action.error && <Notice tone="danger" title="Not saved">{action.error}</Notice>}
              <Nav onBack={() => goTo(5)} onNext={() => void finish()} nextLabel={action.busy ? "Saving…" : "Save account"} nextDisabled={action.busy} />
            </Section>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function restoreAfterOauth(result: string | null): { step: number; state: WizardState } {
  if (!result) return { step: 0, state: EMPTY };
  let restored: WizardState | null = null;
  try {
    restored = JSON.parse(window.sessionStorage.getItem(SAVED) ?? "null") as WizardState | null;
  } catch {
    restored = null;
  }
  if (!restored) return { step: 0, state: EMPTY };
  return { step: result === "connected" ? 3 : 2, state: { ...restored, useOauth: result === "connected" } };
}

const ENV_TEXT: Record<AccountEnvironment, string> = {
  PAPER: "Simulated by 2kFX. No broker, no money.",
  DEMO: "A broker account funded with virtual money. The safest way to test with real market prices.",
  LIVE: "Real money at the broker.",
  UNKNOWN: "",
};

const AUTH_HINT: Record<ConnectorType, string> = {
  paper: "The defaults are fine to start learning.",
  deriv: "Use “Sign in with Deriv”, or paste a personal access token with the trade scope from your Deriv account settings.",
  mt5_bridge: "The bridge runs on a Windows PC or VPS next to MetaTrader 5 (see docs/MT5_BRIDGE_SETUP.md).",
};

function Stepper({ step }: { step: number }) {
  return (
    <ol className="my-6 flex flex-wrap gap-x-1 gap-y-2" aria-label="Progress">
      {STEPS.map((label, i) => (
        <li key={label} className="flex items-center gap-1" aria-current={i === step ? "step" : undefined}>
          <span className={cn("num flex size-6 items-center justify-center rounded-full text-xs",
            i < step ? "bg-positive/15 text-positive" : i === step ? "bg-accent text-canvas" : "bg-surface-raised text-fg-subtle")}>
            {i < step ? <Check className="size-3.5" aria-hidden /> : i + 1}
          </span>
          <span className={cn("hidden text-xs md:inline", i === step ? "text-fg" : "text-fg-subtle")}>{label}</span>
          {i < STEPS.length - 1 && <span className="mx-1 hidden h-px w-4 bg-line md:inline-block" aria-hidden />}
        </li>
      ))}
    </ol>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-fg">{title}</h2>
        {hint && <p className="mt-1 text-sm text-fg-muted">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Nav({ onBack, onNext, nextDisabled, nextLabel = "Continue" }: { onBack?: () => void; onNext: () => void; nextDisabled?: boolean; nextLabel?: string }) {
  return (
    <div className="flex justify-between border-t border-line pt-5">
      {onBack ? <Button variant="ghost" onClick={onBack}>Back</Button> : <span />}
      <Button variant="primary" onClick={onNext} disabled={nextDisabled}>{nextLabel}</Button>
    </div>
  );
}

function Done({ account, onAnother }: { account: Account; onAnother: () => void }) {
  const connected = account.connection_status === "CONNECTED";
  const steps = useMemo(() => [
    "Check the account card on the Brokers page.",
    "Switch “Trading enabled” on when you are ready (it is off now).",
    "Assign a strategy on the Strategies page, or place a manual trade.",
  ], []);
  return (
    <div className="mx-auto max-w-xl py-10 text-center">
      <CircleCheck className="mx-auto size-10 text-positive" aria-hidden />
      <h1 className="mt-4 text-xl font-semibold">{account.label} added</h1>
      <p className="mt-2 text-sm text-fg-muted">
        {connected ? "Connected and synced." : `Saved. Status: ${account.connection_status.toLowerCase()} — ${account.connection_detail ?? ""}`}
      </p>
      <div className="mt-4 flex justify-center gap-2"><EnvBadge env={account.environment} /><Badge tone="neutral">Trading off</Badge></div>
      <ul className="mx-auto mt-6 max-w-sm space-y-2 text-left text-sm text-fg-muted">
        {steps.map((s) => <li key={s} className="flex gap-2"><KeyRound className="mt-0.5 size-4 shrink-0 text-fg-subtle" aria-hidden />{s}</li>)}
      </ul>
      <div className="mt-8 flex justify-center gap-2">
        <Link href="/brokers"><Button variant="primary">Go to Brokers</Button></Link>
        <Button variant="ghost" onClick={onAnother}>Add another</Button>
      </div>
    </div>
  );
}
