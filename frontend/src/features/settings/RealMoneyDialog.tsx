"use client";

import { Check, CircleCheck, Lock, OctagonAlert, ShieldCheck, Square } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import { toast } from "sonner";
import { EnvBadge } from "@/components/app/badges";
import { Money } from "@/components/app/money";
import { ListSkeleton, Notice } from "@/components/app/states";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import {
  blockerFor,
  canAdvance,
  DEFAULT_LIVE_PHRASE,
  errorStep,
  firstStep,
  LIVE_AUTH_STEPS,
  limitSentences,
  type LiveAuthContext,
  type LiveAuthField,
  type LiveAuthStep,
  liveAccounts,
  nextStep,
  previousStep,
  stepIndex,
} from "@/lib/liveAuth";
import { stopTrading as stopTradingRequest } from "@/lib/tradingActions";
import type { RiskProfile, TradingModeRequest, TradingStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Real-money authorisation: a guided, keyboard-usable dialog that walks
 * through every requirement the server enforces for LIVE mode (PUT
 * /api/trading/mode) and explains each blocker before anything is sent.
 * Opened from Settings → Accounts and from the DEMO/LIVE pill in the top bar.
 */
export function RealMoneyDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto border-t-4 border-live ring-live/30 sm:max-w-lg">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-36 bg-[linear-gradient(180deg,color-mix(in_oklab,var(--live)_16%,transparent),transparent)]" />
        {/* Mounted only while open, so each opening starts fresh. */}
        {open && <Flow onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

const TITLES: Record<LiveAuthStep, string> = {
  prepare: "Before you start",
  account: "Choose the real-money account",
  limits: "Check this account's limits",
  warning: "You can lose real money",
  credentials: "Confirm it's you",
  done: "LIVE mode is on",
};

function Flow({ onClose }: { onClose: () => void }) {
  const { status, accounts, reloadStatus, setStatus } = useAppData();
  const { user } = useSession();
  const profiles = useApi<RiskProfile[]>("/risk/profiles");
  const ids = { code: useId(), password: useId(), phrase: useId(), ack: useId() };

  const live = liveAccounts(accounts ?? []);
  const [accountId, setAccountId] = useState<string | null>(() => (live.length === 1 ? live[0]!.id : null));
  const [acknowledged, setAcknowledged] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [password, setPassword] = useState("");
  const [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<{ field: LiveAuthField; message: string } | null>(null);

  const requiredPhrase = status?.live_confirmation_phrase || DEFAULT_LIVE_PHRASE;
  const ctx: LiveAuthContext = {
    locked: status?.live_trading_locked ?? true,
    running: status ? !status.kill_switch_engaged : false,
    mode: status?.trading_mode ?? "DEMO",
    mfaEnabled: user.mfa_enabled,
    accounts: accounts ?? [],
    accountId,
    acknowledged,
    mfaCode,
    password,
    phrase,
    requiredPhrase,
  };
  const [step, setStep] = useState<LiveAuthStep>(() => firstStep(ctx));

  const account = live.find((a) => a.id === accountId) ?? null;
  const profile = account?.risk_profile ? profiles.data?.find((p) => p.id === account.risk_profile!.id) ?? null : null;
  const blocker = blockerFor(step, ctx);

  const go = (next: LiveAuthStep) => {
    setError(null);
    setStep(next);
  };

  const stopTrading = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await stopTradingRequest("Stopped to authorise real-money trading"));
      toast.success("Trading stopped", { description: "Open positions were not closed." });
      go("account");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not stop trading. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!canAdvance("credentials", ctx) || !accountId) return;
    setBusy(true);
    setError(null);
    setFieldError(null);
    const body: TradingModeRequest = { mode: "LIVE", account_id: accountId, password, confirmation_phrase: phrase.trim(), mfa_code: mfaCode.trim() };
    try {
      // The answer is the new status: the pill turns LIVE together with this step.
      const next = await api<TradingStatus>("/trading/mode", { method: "PUT", body });
      setPassword("");
      setMfaCode("");
      setStatus(next);
      setStep("done");
      toast.success("LIVE mode is on", { description: "Trading is still stopped until you press Start." });
    } catch (e) {
      if (!(e instanceof ApiError)) {
        setError("Something went wrong. Try again.");
        return;
      }
      const target = errorStep(e.code);
      if (e.code === "mfa_code_invalid") setMfaCode("");
      if (target.field) {
        setFieldError({ field: target.field, message: target.message });
      } else {
        setError(e.message || target.message);
      }
      if (target.step !== "credentials") {
        await reloadStatus();
        setStep(target.step);
      }
    } finally {
      setBusy(false);
    }
  };

  const fieldErr = (field: LiveAuthField) => (fieldError?.field === field ? fieldError.message : null);

  return (
    <>
      <DialogHeader className="relative">
        <p className="flex items-center gap-2 text-xs font-extrabold tracking-[0.14em] text-live uppercase">
          <span className="flex size-7 items-center justify-center rounded-full bg-live text-live-foreground"><OctagonAlert className="size-4" aria-hidden /></span>
          Real-money trading
        </p>
        <DialogTitle className="mt-2 text-2xl font-extrabold">{TITLES[step]}</DialogTitle>
        <DialogDescription className="sr-only">Step {stepIndex(step) + 1} of {LIVE_AUTH_STEPS.length}: {TITLES[step]}</DialogDescription>
      </DialogHeader>
      <Stepper step={step} />

      <div className="space-y-4" aria-live="polite">
        {step === "prepare" && (
          <PrepareStep blocker={blocker?.code ?? null} message={blocker?.message ?? null} busy={busy} onStop={() => void stopTrading()} />
        )}

        {step === "account" && (
          blocker ? (
            <Notice tone="warning" title="No LIVE account yet">
              {blocker.message}{" "}
              <Link href="/settings?tab=brokers" onClick={onClose} className="font-medium text-fg underline underline-offset-2">Go to Brokers</Link>
            </Notice>
          ) : (
            <>
              <p className="text-fg-muted">Only this account&apos;s risk limits are recorded with your authorisation. Paper and demo accounts pause while LIVE mode is on.</p>
              <RadioGroup value={accountId ?? ""} onValueChange={setAccountId} aria-label="LIVE account" className="gap-2">
                {live.map((a) => {
                  const id = `live-${a.id}`;
                  return (
                    <Label key={a.id} htmlFor={id}
                      className={cn("flex cursor-pointer items-center gap-3 rounded-lg border p-3 font-normal",
                        accountId === a.id ? "border-live/60 bg-live-soft" : "border-line hover:bg-muted/50")}>
                      <RadioGroupItem id={id} value={a.id} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-fg">{a.label}</span>
                        <span className="block truncate text-xs text-fg-muted">
                          {a.broker} · <span className="num">{a.broker_account_id}</span> · {a.risk_profile ? `Risk profile: ${a.risk_profile.name}` : "No risk profile"}
                        </span>
                      </span>
                      <span className="flex shrink-0 flex-col items-end gap-1">
                        <EnvBadge env="LIVE" />
                        <Money value={a.balance} currency={a.currency} className="text-xs text-fg-muted" />
                      </span>
                    </Label>
                  );
                })}
              </RadioGroup>
            </>
          )
        )}

        {step === "limits" && account && (
          blocker ? (
            <Notice tone="warning" title="No risk profile">
              {blocker.message}{" "}
              <Link href="/settings?tab=accounts" onClick={onClose} className="font-medium text-fg underline underline-offset-2">Go to Settings → Accounts</Link>
            </Notice>
          ) : profiles.error ? (
            <Notice tone="danger" title="Couldn't load the risk profile" action={<Button size="sm" variant="outline" onClick={() => void profiles.reload()}>Retry</Button>}>{profiles.error}</Notice>
          ) : !profile ? (
            <ListSkeleton rows={4} />
          ) : (
            <>
              <p className="text-fg-muted">
                <span className="font-medium text-fg">{account.label}</span> uses the <span className="font-medium text-fg">{profile.name}</span> risk profile. In plain words:
              </p>
              <ul className="space-y-1.5" aria-label="Risk limits">
                {limitSentences(profile, account.currency).map((s) => (
                  <li key={s.key} className={cn("flex gap-2", s.tone === "warning" ? "text-warning" : "text-fg")}>
                    {s.tone === "warning" ? <OctagonAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> : <Check className="mt-0.5 size-4 shrink-0 text-positive" aria-hidden />}
                    <span>{s.text}</span>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-fg-subtle">
                Want different limits? Change them in{" "}
                <Link href="/settings?tab=risk" onClick={onClose} className="underline underline-offset-2">Settings → Risk limits</Link> first.
              </p>
            </>
          )
        )}

        {step === "warning" && (
          <>
            <div role="alert" className="rounded-lg border-2 border-live/60 bg-live-soft p-4">
              <p className="flex items-center gap-2 text-base font-extrabold text-live"><OctagonAlert className="size-5" aria-hidden /> Real money is at risk</p>
              <p className="mt-2 text-fg">
                You can lose your entire trading balance. Automated strategies can and do lose money. Past and backtest results do not guarantee future results.
              </p>
            </div>
            <div className="flex items-start gap-3 rounded-lg bg-surface-raised p-4 ring-1 ring-line">
              <Checkbox id={ids.ack} checked={acknowledged} onCheckedChange={(v) => setAcknowledged(v === true)} className="mt-0.5" />
              <Label htmlFor={ids.ack} className="leading-snug font-medium">I understand I can lose my entire trading balance.</Label>
            </div>
          </>
        )}

        {step === "credentials" && (
          blocker ? (
            <Notice tone="warning" title="Two-factor authentication is off">
              {blocker.message}{" "}
              <Link href="/settings?tab=security" onClick={onClose} className="font-medium text-fg underline underline-offset-2">Set up two-factor authentication first</Link>
            </Notice>
          ) : (
            <form
              id="live-auth-form"
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <FieldBlock id={ids.code} label="Code from your authenticator app" error={fieldErr("mfa_code")}>
                <Input id={ids.code} value={mfaCode} onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  inputMode="numeric" autoComplete="one-time-code" placeholder="6 digits" className="num tracking-widest"
                  aria-invalid={Boolean(fieldErr("mfa_code"))} aria-describedby={fieldErr("mfa_code") ? `${ids.code}-err` : undefined} />
              </FieldBlock>
              <FieldBlock id={ids.password} label="Your password" error={fieldErr("password")}>
                <Input id={ids.password} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
                  aria-invalid={Boolean(fieldErr("password"))} aria-describedby={fieldErr("password") ? `${ids.password}-err` : undefined} />
              </FieldBlock>
              <FieldBlock id={ids.phrase} label={<>Type <span className="num rounded bg-muted px-1.5 py-0.5 font-semibold text-fg select-all">{requiredPhrase}</span> to confirm</>} error={fieldErr("phrase")}>
                <Input id={ids.phrase} value={phrase} onChange={(e) => setPhrase(e.target.value)} autoComplete="off" spellCheck={false}
                  aria-invalid={Boolean(fieldErr("phrase"))} aria-describedby={fieldErr("phrase") ? `${ids.phrase}-err` : undefined} />
                {phrase.length > 0 && phrase.trim() !== requiredPhrase && !fieldErr("phrase") && (
                  <p className="text-xs text-fg-muted">Type it exactly, in capitals.</p>
                )}
              </FieldBlock>
            </form>
          )
        )}

        {step === "done" && (
          <>
            <div className="flex items-center gap-3 rounded-lg border border-live/50 bg-live-soft p-4">
              <CircleCheck className="size-6 shrink-0 text-live" aria-hidden />
              <p className="font-medium text-fg">LIVE mode is on{account ? ` for ${account.label}` : ""}.</p>
            </div>
            <ul className="space-y-2 text-fg-muted">
              <li className="flex gap-2"><Square className="mt-0.5 size-4 shrink-0" aria-hidden /> Trading is still stopped. Nothing trades until you press <span className="font-medium text-fg">Start</span>.</li>
              <li className="flex gap-2"><OctagonAlert className="mt-0.5 size-4 shrink-0 text-live" aria-hidden /> Only LIVE accounts trade now. Paper and demo accounts pause.</li>
              <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden /> You can go back any time with <span className="font-medium text-fg">Return to Demo</span> (top bar or Settings → Accounts).</li>
            </ul>
          </>
        )}

        {error && <Notice tone="danger">{error}</Notice>}
      </div>

      <DialogFooter className="gap-2 sm:justify-between">
        {step !== "done" && step !== "prepare" && step !== firstStep(ctx) ? (
          <Button variant="ghost" onClick={() => go(previousStep(step))} disabled={busy}>Back</Button>
        ) : <span className="hidden sm:block" />}
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          {step === "done" ? (
            <Button onClick={onClose}>Done</Button>
          ) : (
            <>
              <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
              {step === "credentials" ? (
                <Button type="submit" form="live-auth-form" disabled={busy || !canAdvance(step, ctx)}
                  className="bg-live text-live-foreground hover:bg-live/90">
                  {busy ? "Turning on…" : "Turn on LIVE mode"}
                </Button>
              ) : (blocker === null || step !== "prepare") && (
                <Button onClick={() => go(nextStep(step))} disabled={busy || !canAdvance(step, ctx)}>Continue</Button>
              )}
            </>
          )}
        </div>
      </DialogFooter>
    </>
  );
}

function PrepareStep({ blocker, message, busy, onStop }: { blocker: string | null; message: string | null; busy: boolean; onStop: () => void }) {
  if (blocker === "live_locked") {
    return (
      <Notice tone="info" title="Locked on this server">
        <span className="flex items-start gap-2"><Lock className="mt-0.5 size-4 shrink-0" aria-hidden />{message}</span>
      </Notice>
    );
  }
  if (blocker === "already_live") {
    return <Notice tone="live" title="LIVE mode is already on">Use Return to Demo (top bar or Settings → Accounts) to switch back to virtual money.</Notice>;
  }
  if (blocker === "stop_first") {
    return (
      <Notice tone="warning" title="Stop trading first" action={<Button size="sm" onClick={onStop} disabled={busy}>{busy ? "Stopping…" : "Stop trading"}</Button>}>
        The mode can only change while trading is stopped. Stopping blocks new trades; open positions stay open.
      </Notice>
    );
  }
  return <Notice tone="success" title="Ready">Trading is stopped, so the mode can change.</Notice>;
}

function FieldBlock({ id, label, error, children }: { id: string; label: React.ReactNode; error: string | null; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="flex-wrap">{label}</Label>
      {children}
      {error && <p id={`${id}-err`} role="alert" className="text-sm text-negative">{error}</p>}
    </div>
  );
}

function Stepper({ step }: { step: LiveAuthStep }) {
  const current = stepIndex(step);
  return (
    <ol className="flex items-center gap-1" aria-label="Progress">
      {LIVE_AUTH_STEPS.map((s, i) => (
        <li key={s.step} className="flex flex-1 flex-col gap-1" aria-current={i === current ? "step" : undefined}>
          <span className={cn("h-1.5 rounded-full transition-colors", i < current ? "bg-live/60" : i === current ? "bg-live" : "bg-surface-hover")} aria-hidden />
          <span className={cn("hidden text-[11px] sm:block", i === current ? "font-medium text-fg" : "text-fg-subtle")}>
            {s.label}
            <span className="sr-only">{i < current ? " (done)" : i === current ? " (current)" : ""}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
