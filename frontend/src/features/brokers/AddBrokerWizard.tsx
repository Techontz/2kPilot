"use client";

import { ArrowLeft, Check, CircleCheck, ExternalLink, FlaskConical, Home, Landmark, LayoutTemplate, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useId, useState } from "react";
import { toast } from "sonner";
import { EnvBadge, Pill } from "@/components/app/badges";
import { Money } from "@/components/app/money";
import { ErrorState, KeyValue, ListSkeleton, Notice } from "@/components/app/states";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Account, AccountEnvironment, ConnectionTestResult, Connector, ConnectorField, ConnectorType, DerivAccount, RiskProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS = ["Choose broker", "Account type", "Sign in", "Test connection", "Verify account", "Risk profile", "Finish"] as const;
const ICONS: Record<ConnectorType, typeof Landmark> = { paper: FlaskConical, deriv: Landmark };
const SAVED = "tp.add-broker";

interface WizardState {
  connector: ConnectorType | null;
  environment: AccountEnvironment | null;
  values: Record<string, string>;
  useOauth: boolean;
  derivAccountId: string;
}

const EMPTY: WizardState = { connector: null, environment: null, values: {}, useOauth: false, derivAccountId: "" };

const OAUTH_RESULT: Record<string, { tone: "success" | "warning" | "danger"; title: string; text: string }> = {
  connected: { tone: "success", title: "Signed in with Deriv", text: "Now find your Deriv accounts and pick the one to add." },
  cancelled: { tone: "warning", title: "Deriv sign-in was cancelled", text: "Try again, or paste a personal access token instead." },
  invalid: { tone: "danger", title: "Deriv sign-in expired", text: "The sign-in took too long or came from another tab. Start it again." },
  failed: { tone: "danger", title: "Deriv sign-in failed", text: "Deriv did not accept the sign-in. Try again, or use a personal access token." },
  signed_out: { tone: "warning", title: "You were signed out of 2kPilot", text: "Your 2kPilot session ended while you were on Deriv. Sign in again, then start “Sign in with Deriv” again." },
};

interface Catalog {
  connectors: Connector[];
  vault_configured: boolean;
  deriv_signed_in: boolean;
}

/**
 * Settings → Brokers → Add broker, in seven plain steps. Nothing is saved
 * until the last step, which tests the connection again: a failed connection
 * never appears as connected.
 */
export function AddBrokerWizard() {
  const router = useRouter();
  const params = useSearchParams();
  const { reloadAccounts, selectAccount } = useAppData();
  const catalog = useApi<Catalog>("/brokers/connectors");
  const profiles = useApi<RiskProfile[]>("/risk/profiles");
  const oauthResult = params.get("deriv");
  // Returning from "Sign in with Deriv" (?deriv=…): restore the wizard and continue.
  const [returned] = useState(() => restoreAfterOauth(oauthResult));
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
  const ids = { ack: useId(), confirm: useId(), profile: useId(), label: useId() };

  const connector = catalog.data?.connectors.find((c) => c.id === state.connector) ?? null;
  const defaultProfileId = profiles.data?.find((p) => p.name === "Beginner")?.id ?? profiles.data?.[0]?.id ?? "";
  const profileId = riskProfileId || defaultProfileId;
  const profile = profiles.data?.find((p) => p.id === profileId) ?? null;

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

  const setValue = (name: string, value: string) =>
    setState((s) => ({ ...s, useOauth: name === "token" ? false : s.useOauth, values: { ...s.values, [name]: value } }));

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
      try {
        window.sessionStorage.removeItem(SAVED);
      } catch {
        // storage unavailable
      }
      await reloadAccounts();
      selectAccount(result.id);
      setSaved(result);
      toast.success(`${result.label} added`, { description: "Home and History now show this account." });
    }
  };

  const startOauth = async () => {
    try {
      window.sessionStorage.setItem(SAVED, JSON.stringify({ ...state, values: {} }));
    } catch {
      // storage unavailable: the wizard restarts after sign-in
    }
    const result = await action.run(() => api<{ url: string }>("/brokers/deriv/oauth/start", { method: "POST" }));
    if (result) window.location.assign(result.url);
  };

  if (catalog.error && !catalog.data) {
    return <Shell><ErrorState message={catalog.error} onRetry={() => void catalog.reload()} /></Shell>;
  }
  if (!catalog.data) {
    return <Shell><Card><CardContent><ListSkeleton rows={3} /></CardContent></Card></Shell>;
  }
  if (saved) {
    return (
      <Done
        account={saved}
        onAnother={() => {
          setSaved(null);
          setState(EMPTY);
          setTest(null);
          setDerivAccounts(null);
          setLabel("");
          goTo(0);
          router.replace("/settings/brokers/new");
        }}
      />
    );
  }

  // Paper first: the obvious beginner choice.
  const connectors = [...catalog.data.connectors].sort((a, b) => (a.id === "paper" ? -1 : b.id === "paper" ? 1 : 0));
  const oauthNotice = oauthResult ? OAUTH_RESULT[oauthResult] : undefined;

  return (
    <Shell>
      <Stepper step={step} />
      {!catalog.data.vault_configured && (
        <Notice tone="danger" title="Credential encryption is not configured" className="mb-4">
          Run <span className="num font-medium">php artisan tp:keys</span> in backend/ so broker secrets can be stored encrypted.
        </Notice>
      )}
      {oauthNotice && step <= 3 && (
        <Notice tone={oauthNotice.tone} title={oauthNotice.title} className="mb-4">{oauthNotice.text}</Notice>
      )}

      <Card className="gap-0 py-0">
        <CardContent className="space-y-5 p-4 sm:p-6">
          {step === 0 && (
            <Section title="Which broker?" hint="New here? Start with Paper. You can add as many accounts as you like later.">
              <div className="grid gap-3 sm:grid-cols-2" role="group" aria-label="Broker">
                {connectors.map((c) => {
                  const Icon = ICONS[c.id] ?? Landmark;
                  const selected = state.connector === c.id;
                  return (
                    <button
                      key={c.id}
                      type="button"
                      disabled={c.status !== "available"}
                      aria-pressed={selected}
                      onClick={() => setState({ ...EMPTY, connector: c.id, environment: c.environments.length === 1 ? c.environments[0]! : null })}
                      className={cn(
                        "flex flex-col items-start rounded-lg p-4 text-left ring-1 transition-[background-color,box-shadow] outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60",
                        selected ? "bg-[color-mix(in_oklab,var(--primary)_8%,transparent)] ring-2 ring-primary" : "bg-surface-raised ring-line hover:bg-surface-hover",
                      )}
                    >
                      <span className="flex w-full items-center justify-between gap-2">
                        <Icon className={cn("size-5", selected ? "text-brand-ink" : "text-fg-muted")} aria-hidden />
                        {c.id === "paper" && <Pill tone="primary">Best for beginners</Pill>}
                        {c.status !== "available" && <Pill tone="warning">Needs setup</Pill>}
                      </span>
                      <span className="mt-3 text-sm font-semibold text-fg">{c.name}</span>
                      <span className="mt-1 text-xs leading-relaxed text-fg-muted">
                        {c.id === "paper" ? "Paper — practice with simulated money, no sign-up." : c.tagline}
                      </span>
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
              <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Account type">
                {connector.environments.map((env) => (
                  <button
                    key={env}
                    type="button"
                    role="radio"
                    aria-checked={state.environment === env}
                    onClick={() => setState({ ...state, environment: env })}
                    className={cn(
                      "rounded-lg p-4 text-left ring-1 transition-[background-color,box-shadow] outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      state.environment === env ? (env === "LIVE" ? "bg-live-soft ring-2 ring-live" : "bg-[color-mix(in_oklab,var(--primary)_8%,transparent)] ring-2 ring-primary") : "bg-surface-raised ring-line hover:bg-surface-hover",
                    )}
                  >
                    <EnvBadge env={env} />
                    <p className="mt-2 text-sm text-fg-muted">{ENV_TEXT[env]}</p>
                  </button>
                ))}
              </div>
              {state.environment === "LIVE" && (
                <Notice tone="live" title="Real money">
                  A LIVE account can be added for monitoring. It can only trade after you authorise real-money trading (Settings → Accounts), with two-factor authentication — and never while the server lock is on.
                  <span className="mt-3 flex items-center gap-3">
                    <Switch id={ids.ack} checked={ackLive} onCheckedChange={setAckLive} />
                    <Label htmlFor={ids.ack} className="text-fg">I understand this account holds real money.</Label>
                  </span>
                </Notice>
              )}
              <Nav onBack={() => goTo(0)} onNext={() => goTo(2)} nextDisabled={!state.environment || (state.environment === "LIVE" && !ackLive)} />
            </Section>
          )}

          {step === 2 && connector && (
            <Section title={connector.id === "paper" ? "Simulation settings" : "Sign in"} hint={AUTH_HINT[connector.id]}>
              {connector.id === "deriv" && connector.auth_methods.includes("oauth") && (
                <div className="rounded-lg bg-surface-raised p-4 ring-1 ring-line">
                  <p className="text-sm font-medium text-fg">Sign in with Deriv</p>
                  <p className="mt-1 text-sm text-fg-muted">You log in on deriv.com and come back here. 2kPilot never sees your Deriv password, and the token stays on the server.</p>
                  {state.useOauth ? (
                    <p className="mt-3 flex items-center gap-1.5 text-sm text-positive"><CircleCheck className="size-4" aria-hidden /> Signed in</p>
                  ) : (
                    <Button className="mt-3" onClick={() => void startOauth()} disabled={action.busy}><ExternalLink aria-hidden /> Sign in with Deriv</Button>
                  )}
                  <p className="mt-3 text-xs text-fg-subtle">Deriv sign-ins last about an hour. For a robot that runs all day, a personal access token (below) is more reliable.</p>
                </div>
              )}
              {connector.id === "deriv" && <p className="text-xs font-medium tracking-wide text-fg-subtle uppercase">Or use a personal access token</p>}
              <div className="grid gap-4 sm:grid-cols-2">
                {connector.fields.map((field) => (
                  <ConnectorInput key={field.name} field={field} value={state.values[field.name]} onChange={(v) => setValue(field.name, v)} />
                ))}
              </div>
              {action.error && <Notice tone="danger">{action.error}</Notice>}
              <Nav onBack={() => goTo(1)} onNext={() => goTo(3)} nextDisabled={connector.id === "deriv" && !state.useOauth && !(state.values.token ?? "").trim()} />
            </Section>
          )}

          {step === 3 && connector && (
            <Section title="Test the connection" hint="2kPilot asks the broker for this account's details. Nothing is saved yet.">
              {connector.id === "deriv" && (
                <div className="space-y-3">
                  <Button variant="outline" onClick={() => void listDerivAccounts()} disabled={action.busy}>
                    {derivAccounts ? "Refresh accounts" : "Find my Deriv accounts"}
                  </Button>
                  {derivAccounts && (
                    <div role="radiogroup" aria-label="Deriv account" className="space-y-2">
                      {derivAccounts.length === 0 && <p className="text-sm text-fg-muted">This sign-in can&apos;t reach any Deriv Options account.</p>}
                      {derivAccounts.map((d) => {
                        const env: AccountEnvironment = d.account_type === "demo" ? "DEMO" : "LIVE";
                        const matches = env === state.environment;
                        const checked = state.derivAccountId === d.account_id;
                        return (
                          <button
                            key={d.account_id}
                            type="button"
                            role="radio"
                            aria-checked={checked}
                            disabled={!matches}
                            onClick={() => setState({ ...state, derivAccountId: d.account_id })}
                            className={cn(
                              "flex w-full items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
                              checked ? "border-primary bg-primary/5" : "border-line hover:bg-muted/50",
                            )}
                          >
                            <span className="min-w-0">
                              <span className="num block truncate text-sm text-fg">{d.account_id}</span>
                              <span className="block truncate text-xs text-fg-subtle">
                                {matches ? `${d.account_type === "demo" ? "Demo" : "Real money"} · ${d.currency}` : `You chose ${state.environment} in step 2`}
                              </span>
                            </span>
                            <span className="flex shrink-0 items-center gap-2">
                              <Money value={d.balance} currency={d.currency} className="text-sm text-fg" />
                              <EnvBadge env={env} />
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
              {connector.id === "paper" && <p className="text-sm text-fg-muted">Paper needs no sign-in. Press Test connection to start the simulator.</p>}
              {action.error && <Notice tone="danger" title="The connection did not work">{action.error}</Notice>}
              <Nav
                onBack={() => goTo(2)}
                onNext={() => void runTest()}
                nextLabel="Test connection"
                busyLabel="Testing…"
                busy={action.busy}
                nextDisabled={action.busy || (connector.id === "deriv" && !state.derivAccountId)}
              />
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
                ["Balance", <Money key="b" value={test.account.balance} currency={test.account.currency} />],
                ["Equity", <Money key="q" value={test.account.equity} currency={test.account.currency} />],
                ["Instruments", `${test.symbol_count} (${Object.entries(test.categories).map(([k, v]) => `${v} ${k}`).join(", ") || "—"})`],
                ["Trading allowed", test.account.trade_allowed ? "Yes" : "No — the broker reports trading is not allowed"],
                ["Order types", test.capabilities.pending_orders === false ? "Market orders only" : "Market and pending orders"],
              ]} />
              {test.capabilities.notes?.map((n) => <p key={n} className="text-xs text-fg-subtle">• {n}</p>)}
              {test.warnings.map((w) => <Notice key={w} tone="warning">{w}</Notice>)}
              <div className="flex items-center gap-3 rounded-lg bg-surface-raised p-3 ring-1 ring-line">
                <Switch id={ids.confirm} checked={confirmed} onCheckedChange={setConfirmed} />
                <Label htmlFor={ids.confirm}>This is the account I want to add.</Label>
              </div>
              <Nav onBack={() => goTo(3)} onNext={() => goTo(5)} nextDisabled={!confirmed} />
            </Section>
          )}

          {step === 5 && (
            <Section title="Assign a risk profile" hint="The limits every trade on this account must pass — stake per trade, daily loss, losses in a row. You can change them any time in Settings → Risk limits.">
              {profiles.error ? (
                <ErrorState message={profiles.error} onRetry={() => void profiles.reload()} />
              ) : (
                <div className="space-y-1.5">
                  <Label htmlFor={ids.profile}>Risk profile</Label>
                  <Select value={profileId} onValueChange={setRiskProfileId} disabled={!profiles.data}>
                    <SelectTrigger id={ids.profile} className="w-full"><SelectValue placeholder="Loading…" /></SelectTrigger>
                    <SelectContent>
                      {profiles.data?.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  {profile && (
                    <p className="text-xs text-fg-muted">
                      Stake per trade {Number(profile.stake_amount)}
                      {profile.max_consecutive_losses ? ` · stops after ${profile.max_consecutive_losses} losses in a row` : ""}
                      {profile.max_trades_per_day ? ` · at most ${profile.max_trades_per_day} trades a day` : ""}
                    </p>
                  )}
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor={ids.label}>Name for this account</Label>
                <Input id={ids.label} value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120}
                  placeholder={connector?.id === "paper" ? "Paper practice" : `${connector?.name ?? ""} ${test?.account.account_id ?? ""}`} />
                <p className="text-xs text-fg-muted">Shown on the account card and in the account switcher.</p>
              </div>
              <Nav onBack={() => goTo(4)} onNext={() => goTo(6)} nextDisabled={!profileId} />
            </Section>
          )}

          {step === 6 && test && (
            <Section title="Finish" hint="2kPilot tests the connection one more time, saves the account with trading switched off, and connects it.">
              <KeyValue items={[
                ["Broker", connector?.name ?? ""],
                ["Account", <span key="a" className="num">{test.account.account_id}</span>],
                ["Type", <EnvBadge key="e" env={test.account.environment} />],
                ["Risk profile", profile?.name ?? "—"],
                ["Trading", "Off until you switch it on"],
              ]} />
              {action.error && <Notice tone="danger" title="Not saved">{action.error}</Notice>}
              <Nav onBack={() => goTo(5)} onNext={() => void finish()} nextLabel="Save account" busyLabel="Saving…" busy={action.busy} nextDisabled={action.busy} />
            </Section>
          )}
        </CardContent>
      </Card>
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-3xl">
      <Link href="/settings?tab=brokers" className="mb-4 inline-flex h-9 items-center gap-1.5 rounded-full bg-surface-hover pr-4 pl-3 text-sm font-bold text-fg-muted transition-colors hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> Brokers
      </Link>
      <p className="eyebrow mt-2 text-brand-ink">Settings · Brokers</p>
      <h1 className="title-xl mt-2 text-4xl text-fg sm:text-5xl">Add broker</h1>
      {children}
    </div>
  );
}

function ConnectorInput({ field, value, onChange }: { field: ConnectorField; value: string | undefined; onChange: (value: string) => void }) {
  const id = useId();
  const wide = field.kind === "password" || field.name === "symbols";
  const current = value ?? (field.secret ? "" : field.default ?? "");
  return (
    <div className={cn("space-y-1.5", wide && "sm:col-span-2")}>
      <Label htmlFor={id}>{field.label}</Label>
      {field.kind === "select" || field.kind === "boolean" ? (
        <Select value={field.kind === "boolean" ? (current || "true") : current} onValueChange={onChange}>
          <SelectTrigger id={id} className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            {field.kind === "boolean"
              ? <><SelectItem value="true">Yes</SelectItem><SelectItem value="false">No</SelectItem></>
              : field.options?.map((o) => <SelectItem key={o} value={o}>{humanize(o)}</SelectItem>)}
          </SelectContent>
        </Select>
      ) : (
        <Input
          id={id}
          type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"}
          inputMode={field.kind === "number" ? "decimal" : undefined}
          autoComplete={field.secret ? "new-password" : "off"}
          value={current}
          placeholder={field.secret ? "Stored encrypted — never shown again" : undefined}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={field.help ? `${id}-help` : undefined}
          className={cn(field.kind === "number" && "num")}
        />
      )}
      {field.help && <p id={`${id}-help`} className="text-xs text-fg-muted">{field.help}</p>}
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
  PAPER: "Simulated by 2kPilot. No broker, no money.",
  DEMO: "A broker account funded with virtual money. The safest way to test with real market prices.",
  LIVE: "Real money at the broker.",
  UNKNOWN: "",
};

const AUTH_HINT: Record<ConnectorType, string> = {
  paper: "The defaults are fine to start learning.",
  deriv: "Use “Sign in with Deriv”, or paste a personal access token with the trade scope from your Deriv account settings.",
};

function Stepper({ step }: { step: number }) {
  return (
    <div className="my-6">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <p className="text-sm font-bold text-fg">Step <span className="num">{step + 1}</span> of <span className="num">{STEPS.length}</span> · {STEPS[step]}</p>
      </div>
      <ol className="grid grid-cols-7 gap-1.5" aria-label="Progress">
        {STEPS.map((label, i) => (
          <li key={label} className="min-w-0" aria-current={i === step ? "step" : undefined}>
            <span aria-hidden className={cn("block h-1.5 rounded-full transition-colors duration-500", i < step ? "bg-primary/60" : i === step ? "bg-primary" : "bg-surface-hover")} />
            <span className={cn("mt-2 hidden items-center gap-1 truncate text-[11px] md:flex", i === step ? "font-bold text-fg" : i < step ? "text-fg-muted" : "text-fg-subtle")}>
              {i < step && <Check className="size-3 shrink-0 text-brand-ink" aria-hidden />}
              <span className="truncate">{label}</span>
            </span>
            <span className="sr-only md:hidden">{label}</span>
            {i < step && <span className="sr-only"> (done)</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  const id = useId();
  return (
    <section className="space-y-5" aria-labelledby={id}>
      <div>
        <h2 id={id} className="text-xl font-extrabold tracking-tight text-fg">{title}</h2>
        {hint && <p className="mt-1 text-sm text-fg-muted">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Nav({ onBack, onNext, nextDisabled, nextLabel = "Continue", busy, busyLabel }: {
  onBack?: () => void;
  onNext: () => void;
  nextDisabled?: boolean;
  nextLabel?: string;
  busy?: boolean;
  busyLabel?: string;
}) {
  return (
    <div className="flex justify-between gap-2 border-t border-line pt-5">
      {onBack ? <Button variant="ghost" onClick={onBack}>Back</Button> : <span />}
      <Button size="lg" onClick={onNext} disabled={nextDisabled} aria-busy={busy}>
        {busy && busyLabel ? busyLabel : nextLabel}
      </Button>
    </div>
  );
}

function Done({ account, onAnother }: { account: Account; onAnother: () => void }) {
  const connected = account.connection_status === "CONNECTED";
  return (
    <div className="mx-auto max-w-xl py-10 text-center">
      <span className="mx-auto flex size-16 items-center justify-center rounded-full bg-positive-soft"><CircleCheck className="size-9 text-positive" aria-hidden /></span>
      <h1 className="title-xl mt-5 text-3xl text-fg">{account.label} added</h1>
      <p className="mt-2 text-sm text-fg-muted" role="status">
        {connected ? "Connected and synced." : `Saved. Status: ${account.connection_status.toLowerCase()}${account.connection_detail ? ` — ${account.connection_detail}` : ""}`}
      </p>
      <div className="mt-4 flex justify-center gap-2"><EnvBadge env={account.environment} /><Pill>Trading off</Pill></div>
      <ol className="mx-auto mt-6 max-w-sm list-decimal space-y-2 pl-5 text-left text-sm text-fg-muted">
        <li>Pick a strategy (start with a template) and test it.</li>
        <li>Switch “Trading enabled” on for this account in Settings → Accounts.</li>
        <li>Press Start on Home when you are ready.</li>
      </ol>
      <div className="mt-8 flex flex-wrap justify-center gap-2">
        <Button asChild><Link href="/strategies?tab=templates"><LayoutTemplate aria-hidden /> Pick a strategy</Link></Button>
        <Button asChild variant="outline"><Link href="/"><Home aria-hidden /> Go to Home</Link></Button>
        <Button variant="ghost" onClick={onAnother}><Plus aria-hidden /> Add another</Button>
      </div>
    </div>
  );
}
