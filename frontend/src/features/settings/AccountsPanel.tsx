"use client";

import { Cable, CircleCheck, Lock, OctagonAlert, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import { toast } from "sonner";
import { ConnectionDot, connectionLabel, EnvBadge, Pill } from "@/components/app/badges";
import { Money } from "@/components/app/money";
import { CardsSkeleton, EmptyState, ErrorState, Notice, SectionHeader } from "@/components/app/states";
import { Term } from "@/components/app/term";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { stopTrading } from "@/lib/tradingActions";
import type { Account, RiskProfile, TradingStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RealMoneyDialog } from "./RealMoneyDialog";

const NO_PROFILE = "__none__";

/** Settings → Accounts: which account Home/History show, its risk profile, trading on/off, and real money. */
export function AccountsPanel() {
  const { accounts, account: selected, selectAccount, reloadAccounts } = useAppData();
  const profiles = useApi<RiskProfile[]>("/risk/profiles");

  return (
    <div className="space-y-6">
      <RealMoneyCard />
      <section aria-labelledby="accounts-heading">
        <SectionHeader
          title={<span id="accounts-heading">Your accounts</span>}
          description="The account you use is what Home and History show by default. Each account needs a risk profile and its own “Trading enabled” switch before anything can trade on it."
        />
        {accounts === null ? (
          <CardsSkeleton count={2} />
        ) : accounts.length === 0 ? (
          <Card>
            <EmptyState icon={Cable} title="No accounts yet" action={<Button asChild><Link href="/settings/brokers/new">Add broker</Link></Button>}>
              Start with Paper (no money) or connect a Deriv demo account.
            </EmptyState>
          </Card>
        ) : (
          <ul className="grid gap-4 lg:grid-cols-2">
            {accounts.map((a) => (
              <li key={a.id} className="min-w-0">
                <AccountSettingsCard
                  account={a}
                  selected={a.id === selected?.id}
                  onSelect={() => {
                    selectAccount(a.id);
                    toast.success(`Using ${a.label}`, { description: "Home and History now show this account." });
                  }}
                  profiles={profiles.data}
                  profilesError={profiles.error}
                  onRetryProfiles={() => void profiles.reload()}
                  onChanged={() => void reloadAccounts()}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function AccountSettingsCard({
  account,
  selected,
  onSelect,
  profiles,
  profilesError,
  onRetryProfiles,
  onChanged,
}: {
  account: Account;
  selected: boolean;
  onSelect: () => void;
  profiles: RiskProfile[] | null;
  profilesError: string | null;
  onRetryProfiles: () => void;
  onChanged: () => void;
}) {
  const ids = { profile: useId(), trading: useId() };
  const [busy, setBusy] = useState<"profile" | "trading" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const patch = async (what: "profile" | "trading", body: Record<string, unknown>, success: string) => {
    setBusy(what);
    setError(null);
    try {
      await api<Account>(`/accounts/${account.id}`, { method: "PATCH", body });
      toast.success(success);
      onChanged();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Could not save. Try again.";
      setError(message);
      toast.error("Not changed", { description: message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      role="article"
      aria-label={`${account.label} account`}
      className={cn("h-full gap-0 py-0", selected && "ring-2 ring-primary/50", account.environment === "LIVE" && "border-t-2 border-t-live")}
    >
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <ConnectionDot status={account.connection_status} />
              <h3 className="truncate font-semibold text-fg">{account.label}</h3>
            </div>
            <p className="mt-0.5 truncate text-xs text-fg-muted">
              {account.broker} · <span className="num">{account.broker_account_id}</span> · {connectionLabel(account.connection_status)}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <EnvBadge env={account.environment} />
            <Money value={account.balance} currency={account.currency} className="text-sm font-medium text-fg" />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {selected ? (
            <Pill tone="primary"><CircleCheck className="size-3" aria-hidden /> In use on Home and History</Pill>
          ) : (
            <Button size="sm" variant="outline" onClick={onSelect}>Use this account</Button>
          )}
        </div>

        <div className="space-y-1.5 border-t border-line pt-4">
          <Label htmlFor={ids.profile}>Risk profile</Label>
          {profilesError ? (
            <ErrorState message={profilesError} onRetry={onRetryProfiles} />
          ) : (
            <Select
              value={account.risk_profile?.id ?? NO_PROFILE}
              disabled={busy !== null || profiles === null}
              onValueChange={(v) => void patch("profile", { risk_profile_id: v === NO_PROFILE ? null : v }, "Risk profile saved")}
            >
              <SelectTrigger id={ids.profile} aria-label="Risk profile" className="w-full">
                <SelectValue placeholder={profiles === null ? "Loading…" : "Choose a profile"} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_PROFILE}>None (this account cannot trade)</SelectItem>
                {(profiles ?? []).map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                {account.risk_profile && profiles && !profiles.some((p) => p.id === account.risk_profile!.id) && (
                  <SelectItem value={account.risk_profile.id}>{account.risk_profile.name}</SelectItem>
                )}
              </SelectContent>
            </Select>
          )}
          <p className="text-xs text-fg-muted">The limits every trade on this account must pass: stake, daily loss, losses in a row. Edit them in Risk limits.</p>
        </div>

        <div className="flex items-start justify-between gap-4 border-t border-line pt-4">
          <div className="min-w-0">
            <Label htmlFor={ids.trading}>Trading enabled</Label>
            <p className="mt-1 text-xs text-fg-muted" aria-live="polite">
              {account.trading_enabled
                ? "On: Strategies and manual tickets may trade on this account (the risk engine still decides every trade)."
                : "Off: nothing can trade on this account, even when trading is started."}
            </p>
          </div>
          <Switch
            id={ids.trading}
            aria-label="Trading enabled"
            checked={account.trading_enabled}
            disabled={busy !== null}
            onCheckedChange={(next) => void patch("trading", { trading_enabled: next }, next ? "Trading enabled on this account" : "Trading switched off on this account")}
          />
        </div>
        {error && <Notice tone="danger">{error}</Notice>}
      </CardContent>
    </Card>
  );
}

/** Current mode, the door into LIVE (via the authorisation dialog) and the one-click way back. */
export function RealMoneyCard() {
  const { status, reloadStatus, setStatus } = useAppData();
  const [dialog, setDialog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [needsStop, setNeedsStop] = useState(false);

  if (!status) {
    return <CardsSkeleton count={1} className="md:grid-cols-1 xl:grid-cols-1" />;
  }
  const live = status.trading_mode === "LIVE";
  const locked = status.live_trading_locked;

  const toDemo = async (stopFirst: boolean) => {
    setBusy(true);
    try {
      if (stopFirst) await stopTrading("Returning to Demo");
      setStatus(await api<TradingStatus>("/trading/mode", { method: "PUT", body: { mode: "DEMO" } }));
      setNeedsStop(false);
      toast.success("Back in Demo mode", { description: "Real-money trading is off. Trading is stopped — press Start to trade with virtual money." });
    } catch (e) {
      if (e instanceof ApiError && e.code === "stop_first") {
        setNeedsStop(true);
      } else {
        toast.error("Could not return to Demo", { description: e instanceof ApiError ? e.message : "Try again." });
      }
      await reloadStatus();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card role="region" className={cn("gap-0 py-0", live && "border-2 border-live bg-live-soft")} aria-labelledby="real-money-heading">
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="real-money-heading" className="text-lg font-semibold tracking-tight text-fg">Real-money (LIVE) trading</h2>
            <p className="mt-0.5 max-w-2xl text-sm text-fg-muted">
              {live
                ? "LIVE mode is on: only real-money accounts may trade. Paper and demo accounts are paused."
                : <>You are in <Term id="demoMode">Demo mode</Term>: only Paper and demo accounts can trade. Real money is never touched.</>}
            </p>
          </div>
          <span
            aria-live="polite"
            className={cn("inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-xs font-bold tracking-wider",
              live ? "bg-live text-live-foreground" : "bg-demo-soft text-demo ring-1 ring-demo/30")}
          >
            {live && <span className="size-1.5 rounded-full bg-live-foreground motion-safe:animate-pulse" aria-hidden />}
            {live ? "LIVE — REAL MONEY" : "DEMO"}
          </span>
        </div>

        {!live && status.live_revoked_reason && (
          <Notice tone="warning" title="LIVE mode was turned off">{status.live_revoked_reason} Authorize again to trade with real money.</Notice>
        )}

        {live ? (
          <div className="space-y-3">
            {needsStop ? (
              <>
                <Notice tone="warning" title="Your trading is running">
                  The mode can only change while trading is stopped. Stopping blocks new trades; open positions stay open.
                </Notice>
                <Button size="lg" onClick={() => void toDemo(true)} disabled={busy}>{busy ? "Working…" : "Stop trading and return to Demo"}</Button>
              </>
            ) : (
              <Button size="lg" variant="outline" onClick={() => void toDemo(false)} disabled={busy}>
                <ShieldCheck aria-hidden /> {busy ? "Returning…" : "Return to Demo"}
              </Button>
            )}
            {status.live_authorized_at && (
              <p className="text-xs text-fg-muted">Authorised {new Date(status.live_authorized_at).toLocaleString()}.</p>
            )}
          </div>
        ) : locked ? (
          <div className="space-y-3">
            <Notice tone="info" title="Locked on this server">
              <span className="flex items-start gap-2">
                <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
                Real-money trading is locked on this server. The server administrator must enable it (LIVE_TRADING_ENABLED).
              </span>
            </Notice>
            <Button variant="outline" disabled aria-disabled>Authorize real-money trading…</Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => setDialog(true)} className="bg-live text-live-foreground hover:bg-live/90">
              <OctagonAlert aria-hidden /> Authorize real-money trading…
            </Button>
            <p className="text-xs text-fg-muted">Needs a LIVE account with a risk profile, two-factor authentication, your password and a typed confirmation.</p>
          </div>
        )}
      </CardContent>
      <RealMoneyDialog open={dialog} onOpenChange={setDialog} />
    </Card>
  );
}
