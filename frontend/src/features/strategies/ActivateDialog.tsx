"use client";

import { ArrowRight, CircleCheck, CircleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { EnvBadge } from "@/components/app/badges";
import { Money } from "@/components/app/money";
import { Notice } from "@/components/app/states";
import { useTradingControl } from "@/components/layout/TradingControls";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { availableFamilies, contractProblems, contractSummary, initialContract } from "@/lib/contracts";
import { useAction, useApi } from "@/lib/hooks";
import type { ActivationResult, ContractOffer, ContractSpec, Instrument, RiskProfile, Strategy } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type ContractErrors, ContractFields } from "./ContractFields";

interface InstrumentsResponse {
  instruments: Instrument[];
  connection_status: string;
  simulated: boolean;
}

/**
 * Activate = run this strategy's latest version on one account + market with
 * a contract. Defaults: the selected account, the strategy's suggested market
 * and contract (filtered by what the broker offers), the risk profile's stake.
 * Afterwards it says honestly whether anything will trade, and why not.
 */
export function ActivateDialog({ strategy, open, onOpenChange, onDone }: { strategy: Strategy | null; open: boolean; onOpenChange: (open: boolean) => void; onDone: () => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl">
        {strategy && open && <ActivateForm key={strategy.id} strategy={strategy} onClose={() => onOpenChange(false)} onDone={onDone} />}
      </DialogContent>
    </Dialog>
  );
}

function ActivateForm({ strategy, onClose, onDone }: { strategy: Strategy; onClose: () => void; onDone: () => void }) {
  const { accounts, account: selected } = useAppData();
  const [accountId, setAccountId] = useState(selected?.id ?? accounts?.[0]?.id ?? "");
  const account = accounts?.find((a) => a.id === accountId) ?? null;
  const isDeriv = account?.connector_type === "deriv";
  const profiles = useApi<RiskProfile[]>("/risk/profiles");
  const profile = profiles.data?.find((p) => p.id === account?.risk_profile?.id) ?? null;
  const instruments = useApi<InstrumentsResponse>(accountId ? "/markets/instruments" : null, { account_id: accountId });
  const suggested = useMemo(() => strategy.details?.suggested_symbols ?? [], [strategy.details]);
  const tradable = useMemo(() => (instruments.data?.instruments ?? []).filter((i) => i.trade_allowed), [instruments.data]);

  // Which suggested markets this account really offers a usable contract on.
  const [suggestedOffers, setSuggestedOffers] = useState<{ key: string; offers: Record<string, ContractOffer | null> }>({ key: "", offers: {} });
  const candidates = useMemo(() => suggested.filter((s) => tradable.some((i) => i.name === s || i.canonical === s)), [suggested, tradable]);
  const offersKey = `${accountId}:${candidates.join(",")}`;
  useEffect(() => {
    if (!accountId || candidates.length === 0) return;
    let cancelled = false;
    void Promise.all(candidates.map((s) => api<ContractOffer>("/markets/contracts", { query: { account_id: accountId, symbol: s } }).catch(() => null)))
      .then((list) => {
        if (!cancelled) setSuggestedOffers({ key: offersKey, offers: Object.fromEntries(candidates.map((s, i) => [s, list[i] ?? null])) });
      });
    return () => {
      cancelled = true;
    };
  }, [accountId, candidates, offersKey]);
  const offersReady = suggestedOffers.key === offersKey;
  const usableSuggested = candidates.filter((s) => {
    const o = suggestedOffers.offers[s];
    return o && availableFamilies(o, isDeriv).length > 0;
  });

  const [symbol, setSymbol] = useState("");
  const chosen = symbol || (offersReady ? usableSuggested[0] ?? "" : "");
  const offer = useApi<ContractOffer>(accountId && chosen ? "/markets/contracts" : null, { account_id: accountId, symbol: chosen });
  // The contract starts from the strategy's suggestion for each account+market.
  const [specState, setSpecState] = useState<{ key: string; spec: ContractSpec } | null>(null);
  const specKey = `${accountId}:${chosen}:${offer.data ? "offer" : "none"}`;
  const spec = specState?.key === specKey ? specState.spec : initialContract(strategy.details?.suggested_contract, offer.data, isDeriv);
  const setSpec = (next: ContractSpec) => setSpecState({ key: specKey, spec: next });
  const [customStake, setCustomStake] = useState(false);

  const action = useAction();
  const [result, setResult] = useState<ActivationResult | null>(null);
  const maxStake = profile?.max_stake_amount ? Number(profile.max_stake_amount) : null;
  const local: ContractErrors = offer.data || spec.contract_family === "SPOT" ? contractProblems(spec, offer.data, { isDeriv, maxStake }) : {};
  const server: ContractErrors = Object.fromEntries(Object.entries(action.fieldErrors)
    .filter(([k]) => k.startsWith("contract"))
    .map(([k, v]) => [k.replace(/^contract\./, ""), v[0]])) as ContractErrors;
  const errors = { ...server, ...local };
  const blocked = !account || !account.risk_profile || !chosen || Object.keys(local).length > 0;

  const submit = async () => {
    const body = { account_id: accountId, symbol: chosen, contract: { ...spec, stake: customStake && spec.stake ? spec.stake : null } };
    const res = await action.run(() => api<ActivationResult>(`/strategies/${strategy.id}/activate`, { method: "POST", body }));
    if (res) {
      setResult(res);
      toast.success(`${strategy.name} is active on ${account?.label}`);
      onDone();
    }
  };

  if (result) return <ActivationDone strategy={strategy} result={result} onClose={onClose} />;

  return (
    <>
      <DialogHeader>
        <DialogTitle>Activate {strategy.name}</DialogTitle>
        <DialogDescription>Choose where it trades and how each trade works. You can deactivate it at any time.</DialogDescription>
      </DialogHeader>
      <div className="space-y-6">
        <section className="space-y-2">
          <Label htmlFor="activate-account">Account</Label>
          <Select value={accountId} onValueChange={(v) => { setAccountId(v); setSymbol(""); setCustomStake(false); }}>
            <SelectTrigger id="activate-account" className="w-full"><SelectValue placeholder="Choose an account" /></SelectTrigger>
            <SelectContent>
              {(accounts ?? []).map((a) => <SelectItem key={a.id} value={a.id}>{a.label} · {a.environment}{a.environment === "LIVE" ? " (real money)" : ""}</SelectItem>)}
            </SelectContent>
          </Select>
          {account && (
            <p className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <EnvBadge env={account.environment} /> {account.broker} · balance <Money value={account.balance} currency={account.currency} />
            </p>
          )}
          {accounts && accounts.length === 0 && <Notice tone="warning" title="No account yet">Add a Paper or Deriv demo account first. <Link className="underline" href="/settings/brokers/new">Add an account</Link></Notice>}
          {account?.environment === "LIVE" && <Notice tone="live" title="This is a real-money account">It only trades after you authorise real-money trading, and you can lose money.</Notice>}
          {account && !account.risk_profile && (
            <Notice tone="danger" title="This account has no risk profile">Nothing can trade without limits. <Link className="underline" href="/settings?tab=accounts">Choose a risk profile</Link></Notice>
          )}
        </section>

        <section className="space-y-2">
          <p className="text-sm font-medium text-fg">Market</p>
          {instruments.loading || (candidates.length > 0 && !offersReady) ? <Skeleton className="h-10 w-full" /> : (
            <>
              {usableSuggested.length > 0 && (
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Suggested markets">
                  {usableSuggested.map((s) => (
                    <button key={s} type="button" role="radio" aria-checked={chosen === s} onClick={() => setSymbol(s)}
                      className={cn("rounded-full border px-3 py-1.5 text-sm", chosen === s ? "border-primary bg-primary/10 font-medium text-fg" : "border-line text-fg-muted hover:border-line-strong")}>
                      {tradable.find((i) => i.name === s || i.canonical === s)?.description || s}
                    </button>
                  ))}
                </div>
              )}
              <Select value={chosen} onValueChange={setSymbol}>
                <SelectTrigger aria-label="Market" className="w-full"><SelectValue placeholder={tradable.length ? "Or choose another market…" : "No markets available on this account"} /></SelectTrigger>
                <SelectContent>
                  {tradable.map((i) => <SelectItem key={i.name} value={i.name}>{i.description || i.canonical} ({i.name})</SelectItem>)}
                </SelectContent>
              </Select>
              <p className="text-xs text-fg-subtle">
                {usableSuggested.length > 0 ? "Suggested markets are the ones this strategy was designed for and that this account offers." : suggested.length > 0 ? `This account offers none of the suggested markets (${suggested.join(", ")}); pick another.` : "Pick the market the strategy should watch."}
              </p>
            </>
          )}
        </section>

        {chosen && (
          <section className="space-y-3">
            <p className="text-sm font-medium text-fg">How each trade works</p>
            {offer.loading ? <Skeleton className="h-24 w-full" /> : offer.error ? <Notice tone="warning" title="Couldn't ask the broker what it offers">{offer.error}</Notice> : (
              <ContractFields spec={spec} onChange={setSpec} offer={offer.data} isDeriv={isDeriv} errors={errors} />
            )}
            {offer.data?.notes.map((n) => <p key={n} className="text-xs text-fg-subtle">{n}</p>)}
          </section>
        )}

        {chosen && spec.contract_family !== "SPOT" && account?.risk_profile && (
          <section className="space-y-2 rounded-lg bg-surface-raised p-4">
            <p className="text-sm text-fg">
              Each trade stakes <strong className="num">{profile ? <Money value={profile.stake_amount} currency={account.currency} /> : "…"}</strong> — from your
              {" "}“{account.risk_profile.name}” risk profile. That is the most one trade can lose.
            </p>
            <Label className="flex items-center gap-2 font-normal text-fg-muted">
              <Checkbox checked={customStake} onCheckedChange={(v) => { setCustomStake(v === true); if (v !== true) setSpec({ ...spec, stake: null }); }} />
              Use a different stake for this strategy
            </Label>
            {customStake && (
              <div className="grid gap-1.5 sm:w-48">
                <Label htmlFor="activate-stake">Stake ({account.currency})</Label>
                <Input id="activate-stake" type="number" inputMode="decimal" min={0} step="0.01" className="num" value={spec.stake ?? ""} aria-invalid={Boolean(errors.stake)}
                  onChange={(e) => setSpec({ ...spec, stake: e.target.value === "" ? null : e.target.value })} />
                {errors.stake && <p className="text-xs text-negative">{errors.stake}</p>}
                {maxStake && <p className="text-xs text-fg-subtle">Your profile allows at most <Money value={maxStake} currency={account.currency} />.</p>}
              </div>
            )}
          </section>
        )}

        {chosen && <p className="text-sm text-fg-muted">Summary: <span className="text-fg">{chosen} · {contractSummary({ ...spec, stake: customStake ? spec.stake : null }, { currency: account?.currency, profileStake: profile?.stake_amount })}</span></p>}
        {action.error && !Object.keys(server).length && <Notice tone="danger" title="Not activated">{action.error}</Notice>}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>Cancel</Button>
        <Button onClick={() => void submit()} disabled={blocked || action.busy}>{action.busy ? "Activating…" : "Activate"}</Button>
      </DialogFooter>
    </>
  );
}

const BLOCKER_LINK: Record<string, { href: string; label: string }> = {
  account_trading_disabled: { href: "/settings?tab=accounts", label: "Turn trading on" },
  mode_mismatch: { href: "/settings?tab=accounts", label: "Accounts" },
  live_locked: { href: "/settings?tab=accounts", label: "Real-money settings" },
};

function ActivationDone({ strategy, result, onClose }: { strategy: Strategy; result: ActivationResult; onClose: () => void }) {
  const { requestStart } = useTradingControl();
  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          {result.will_trade ? <CircleCheck className="size-5 text-positive" aria-hidden /> : <CircleAlert className="size-5 text-warning" aria-hidden />}
          {strategy.name} is active
        </DialogTitle>
        <DialogDescription>
          {result.symbol} on {result.account?.label} · {contractSummary(result.contract)}
        </DialogDescription>
      </DialogHeader>
      {result.will_trade ? (
        <Notice tone="success" title="It will trade">The bot checks it every time a candle closes. Every trade still passes your risk limits.</Notice>
      ) : (
        <div className="space-y-3" aria-live="polite">
          <Notice tone="warning" title="It won't trade yet">It is switched on, but nothing will trade until these are sorted:</Notice>
          <ul className="space-y-2">
            {result.blockers.map((b) => (
              <li key={`${b.code}:${b.message}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
                <span className="min-w-0 text-fg">{b.message}</span>
                {b.code === "trading_stopped" ? (
                  <Button size="sm" onClick={() => { onClose(); requestStart(); }} className="bg-positive text-positive-foreground hover:bg-positive/90">Start trading</Button>
                ) : BLOCKER_LINK[b.code] ? (
                  <Button size="sm" variant="outline" asChild><Link href={BLOCKER_LINK[b.code]!.href}>{BLOCKER_LINK[b.code]!.label} <ArrowRight aria-hidden /></Link></Button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}
      {result.contract_check && !result.contract_check.verified && (
        <Notice tone="info" title="The broker couldn't confirm the contract right now">{result.contract_check.detail ?? ""} It is checked again before every trade.</Notice>
      )}
      <DialogFooter>
        <Button variant="outline" asChild><Link href="/">Go to Home</Link></Button>
        <Button onClick={onClose}>Done</Button>
      </DialogFooter>
    </>
  );
}

