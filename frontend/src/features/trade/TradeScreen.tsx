"use client";

import { CircleCheck, CircleX, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Field, Segmented, Select, TextInput } from "@/components/ui/Fields";
import { EnvBadge, KeyValue, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { Term } from "@/components/ui/Term";
import { api, ApiError, idempotencyKey } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatMoney, formatNumber } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { Instrument, Quote, Side, TicketPreview, TicketResult } from "@/lib/types";
import { EmptyAccount } from "../markets/MarketsScreen";

type OrderType = "MARKET" | "LIMIT" | "STOP";

/**
 * Manual trading. The ticket is checked by the SAME risk engine as the robot
 * (preview), and again when submitted. There is no way around it.
 */
export function TradeScreen() {
  const { account, status } = useAppData();
  const { isOwner } = useSession();
  const params = useSearchParams();
  const instruments = useApi<{ instruments: Instrument[] }>(account ? "/markets/instruments" : null, { account_id: account?.id });
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "");
  const [side, setSide] = useState<Side>("BUY");
  const [orderType, setOrderType] = useState<OrderType>("MARKET");
  const [volume, setVolume] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [checked, setChecked] = useState<{ sig: string; preview: TicketPreview | null; error: string | null } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [sent, setSent] = useState<{ sig: string; result: TicketResult } | null>(null);
  const keyRef = useRef<string | null>(null);
  const submit = useAction();

  const list = useMemo(() => (instruments.data?.instruments ?? []).filter((i) => i.trade_allowed), [instruments.data]);
  const activeSymbol = symbol || list[0]?.name || "";

  const quote = useApi<{ quotes: Record<string, Quote> }>(account && activeSymbol ? "/markets/quotes" : null, { account_id: account?.id, symbols: activeSymbol }, 2000);
  const live = quote.data?.quotes[activeSymbol];
  const instrument = list.find((i) => i.name === activeSymbol);
  const digits = instrument?.digits ?? 5;

  // The ticket's identity: a preview or result is only shown for the exact ticket it belongs to.
  const ticket = { account_id: account?.id, symbol: activeSymbol, side, order_type: orderType, volume: volume || null, stop_loss: stopLoss, take_profit: takeProfit || null };
  const sig = JSON.stringify(ticket);
  const ready = !!account && !!activeSymbol && !!stopLoss && Number(stopLoss) > 0;
  const preview = checked?.sig === sig ? checked.preview : null;
  const previewError = checked?.sig === sig ? checked.error : null;
  const result = sent?.sig === sig ? sent.result : null;
  const pipSize = preview?.symbol ? Number(preview.symbol.pip_size) : digits === 3 || digits === 5 ? 10 ** -(digits - 1) : 10 ** -digits;
  const entry = live ? Number(side === "BUY" ? live.ask : live.bid) : null;

  // Live risk check, debounced.
  useEffect(() => {
    if (!ready) return;
    const body = JSON.parse(sig) as Record<string, unknown>;
    const timer = window.setTimeout(async () => {
      try {
        const res = await api<TicketPreview>("/trade/preview", { method: "POST", body });
        setChecked({ sig, preview: res, error: null });
      } catch (e) {
        setChecked({ sig, preview: null, error: e instanceof ApiError ? e.message : "Preview unavailable" });
      }
    }, 450);
    return () => window.clearTimeout(timer);
  }, [ready, sig]);

  if (!account) return <EmptyAccount />;
  const unit = account.capabilities?.volume_unit ?? "lots";
  const pendingSupported = false; // manual tickets are market orders for now (see docs/TRADING.md)
  const setStopPips = (pips: number) => entry && setStopLoss((entry - (side === "BUY" ? 1 : -1) * pips * pipSize).toFixed(digits));
  const setTakePips = (pips: number) => entry && setTakeProfit((entry + (side === "BUY" ? 1 : -1) * pips * pipSize).toFixed(digits));
  const pipsAway = (level: string) => entry && level ? Math.abs(entry - Number(level)) / pipSize : null;
  const canReview = isOwner && !!volume && Number(volume) > 0 && !!stopLoss && preview?.approved === true;

  const send = async () => {
    keyRef.current ??= idempotencyKey(); // one key per confirmation: retries can't double-trade
    const res = await submit.run(() => api<TicketResult>("/trade/orders", { method: "POST", body: {
      ...ticket, account_id: account.id, volume, idempotency_key: keyRef.current, confirm: true,
    } }));
    if (res) {
      setSent({ sig, result: res });
      setConfirming(false);
      keyRef.current = null;
    }
  };

  return (
    <div>
      <PageHeader title="Trade" description="Place a manual order. Every ticket passes the same risk checks as the robot — including STOP TRADING, loss limits and the mandatory stop loss." />
      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="Order ticket" action={<span className="flex items-center gap-2 text-sm text-fg-muted">{account.label} <EnvBadge env={account.environment} /></span>} />
          <CardBody className="space-y-5">
            {status?.kill_switch_engaged && <Notice tone="warning" title="Trading is stopped">New orders will be rejected until you press “Resume trading”.</Notice>}
            {!account.trading_enabled && <Notice tone="warning" title="Trading is off for this account">Switch “Trading enabled” on in Brokers to place orders.</Notice>}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Symbol">
                <Select value={activeSymbol} onChange={(e) => setSymbol(e.target.value)} disabled={!list.length}>
                  {list.map((i) => <option key={i.name} value={i.name}>{i.canonical}{i.canonical !== i.name ? ` (${i.name})` : ""} — {i.description}</option>)}
                </Select>
              </Field>
              <Field label="Order type" hint={pendingSupported ? undefined : "Limit and stop entries are not available for manual tickets yet."}>
                <Segmented label="Order type" value={orderType} onChange={(v) => setOrderType(pendingSupported || v === "MARKET" ? v : "MARKET")}
                  options={[{ value: "MARKET", label: "Market" }, { value: "LIMIT", label: <span className="opacity-40">Limit</span> }, { value: "STOP", label: <span className="opacity-40">Stop</span> }]} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Direction">
              {(["BUY", "SELL"] as const).map((s) => (
                <button key={s} type="button" role="radio" aria-checked={side === s} onClick={() => setSide(s)}
                  className={cn("rounded-xl border px-4 py-3 text-left transition-colors",
                    side === s ? (s === "BUY" ? "border-positive bg-positive-soft" : "border-negative bg-negative-soft") : "border-line hover:border-line-strong")}>
                  <span className={cn("block text-sm font-semibold", s === "BUY" ? "text-positive" : "text-negative")}>{s === "BUY" ? "Buy" : "Sell"}</span>
                  <span className="num block text-lg text-fg">{live ? Number(s === "BUY" ? live.ask : live.bid).toFixed(digits) : "—"}</span>
                  <span className="block text-xs text-fg-subtle">{s === "BUY" ? "Profit if the price rises" : "Profit if the price falls"}</span>
                </button>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label={<>Position size ({unit})</>} hint={preview?.suggested_volume ? <button type="button" className="text-accent hover:underline" onClick={() => setVolume(Number(preview.suggested_volume).toString())}>Use max allowed: {Number(preview.suggested_volume)}</button> : "Set a stop loss to see the size your risk profile allows."}>
                <TextInput inputMode="decimal" value={volume} onChange={(e) => setVolume(e.target.value)} placeholder="0.10" className="num" />
              </Field>
              <Field label={<Term id="stopLoss" />} hint={stopLoss ? `${formatNumber(pipsAway(stopLoss), 1)} pips from entry` : <QuickPips onPick={setStopPips} disabled={entry === null} />}>
                <TextInput inputMode="decimal" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} placeholder="required" className="num" aria-required />
              </Field>
              <Field label={<Term id="takeProfit" />} hint={takeProfit ? `${formatNumber(pipsAway(takeProfit), 1)} pips from entry` : <QuickPips onPick={setTakePips} values={[20, 40, 100]} disabled={entry === null} />}>
                <TextInput inputMode="decimal" value={takeProfit} onChange={(e) => setTakeProfit(e.target.value)} placeholder="optional" className="num" />
              </Field>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
              <p className="text-xs text-fg-subtle">You will see a summary before anything is sent.</p>
              <Button variant="primary" disabled={!canReview} onClick={() => { submit.reset(); setConfirming(true); }}>Review order</Button>
            </div>
            {result && <ResultPanel result={result} currency={account.currency} />}
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Risk check" description="Live result from the risk engine" action={<ShieldCheck className="size-4 text-fg-subtle" aria-hidden />} />
          <CardBody className="space-y-4">
            {!stopLoss ? <p className="text-sm text-fg-muted">Enter a stop loss — every order needs one — to see the estimated risk and the risk checks.</p>
              : previewError ? <Notice tone="danger">{previewError}</Notice>
              : !preview ? <p className="text-sm text-fg-subtle">Checking…</p>
              : (
                <>
                  <div className={cn("flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium", preview.approved ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative")}>
                    {preview.approved ? <CircleCheck className="size-4" aria-hidden /> : <CircleX className="size-4" aria-hidden />}
                    {preview.approved ? "Allowed by your risk profile" : preview.rejection_reason}
                  </div>
                  <KeyValue items={[
                    ["Entry (now)", preview.entry_price ? Number(preview.entry_price).toFixed(digits) : "—"],
                    [<Term key="r" id="openRisk">Estimated risk</Term>, preview.risk_amount ? formatMoney(preview.risk_amount, account.currency) : "—"],
                    ["Potential reward", preview.reward_amount ? formatMoney(preview.reward_amount, account.currency) : "—"],
                    [<Term key="rr" id="riskReward" />, preview.reward_risk ? `1 : ${Number(preview.reward_risk).toFixed(2)}` : "—"],
                    [<Term key="s" id="spread" />, preview.spread ? Number(preview.spread).toFixed(digits) : "—"],
                  ]} />
                  <ul className="space-y-1.5 text-sm">
                    {[...preview.checks].sort((a, b) => Number(a.passed) - Number(b.passed)).map((c) => (
                      <li key={c.rule} className="flex gap-2">
                        {c.passed ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-positive" aria-label="passed" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-negative" aria-label="failed" />}
                        <span><span className="text-fg">{c.rule}</span> <span className="text-fg-subtle">— {c.detail}</span></span>
                      </li>
                    ))}
                  </ul>
                  {preview.notes.map((n) => <p key={n} className="text-xs text-fg-subtle">{n}</p>)}
                </>
              )}
          </CardBody>
        </Card>
      </div>

      <ConfirmDialog open={confirming} title={`${side === "BUY" ? "Buy" : "Sell"} ${volume} ${unit} ${instrument?.canonical ?? activeSymbol}?`} confirmLabel={`Send ${side === "BUY" ? "buy" : "sell"} order`}
        confirmVariant={account.environment === "LIVE" ? "danger" : "primary"} busy={submit.busy} error={submit.error} onCancel={() => setConfirming(false)} onConfirm={() => void send()}>
        {account.environment === "LIVE" && <p className="font-semibold text-live">This is a LIVE account. Real money.</p>}
        {account.environment === "PAPER" && <p>PAPER account — simulated execution, no real money.</p>}
        <KeyValue items={[
          ["Account", `${account.label} (${account.environment})`],
          ["Order", `${orderType.toLowerCase()} ${side.toLowerCase()} ${volume} ${unit}`],
          ["Stop loss", stopLoss], ["Take profit", takeProfit || "—"],
          ["Estimated risk", preview?.risk_amount ? formatMoney(preview.risk_amount, account.currency) : "—"],
        ]} />
        <p className="text-xs">The risk engine checks the order again when it is sent. The price you get may differ slightly from the price shown.</p>
      </ConfirmDialog>
    </div>
  );
}

function QuickPips({ onPick, values = [10, 20, 50], disabled }: { onPick: (pips: number) => void; values?: number[]; disabled?: boolean }) {
  return (
    <span className="flex gap-2">
      {values.map((v) => <button key={v} type="button" disabled={disabled} className="text-accent hover:underline disabled:text-fg-subtle disabled:no-underline" onClick={() => onPick(v)}>{v} pips</button>)}
    </span>
  );
}

function ResultPanel({ result, currency }: { result: TicketResult; currency: string }) {
  if (result.status === "EXECUTED") {
    return (
      <Notice tone="success" title={result.order?.is_simulated ? "PAPER order filled" : "Order filled"}>
        Filled at {result.order?.fill_price ?? "—"} · risk {formatMoney(result.risk_amount, currency)}. <Link href="/positions" className="underline">View positions</Link>
      </Notice>
    );
  }
  return (
    <Notice tone={result.status === "REJECTED" ? "warning" : "danger"} title={result.status === "REJECTED" ? "Rejected by the risk engine — nothing was sent" : `Order ${result.status.toLowerCase()}`}>
      {result.rejection_reason ?? result.order?.broker_message ?? "See the journal for details."}
    </Notice>
  );
}
