"use client";

import { CircleCheck, CircleX } from "lucide-react";
import type { ReactNode } from "react";
import { Direction, EnvBadge, OutcomeBadge } from "@/components/app/badges";
import { PnlText } from "@/components/app/money";
import { ErrorState, KeyValue, ListSkeleton } from "@/components/app/states";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { durationText, sizeText, tradeContractLabel } from "@/lib/contracts";
import { formatCurrency, formatDateTime, formatDuration, formatPrice, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Evaluation, JournalEvent, Order, RiskCheck, Signal, Trade } from "@/lib/types";

interface Chain {
  trade: Trade;
  signal: (Signal & { risk_checks: RiskCheck[] }) | null;
  evaluation: Evaluation | null;
  orders: Order[];
  events: JournalEvent[];
}

/**
 * One trade, start to finish: what it was, how it ended, and why the bot took
 * it (market check → signal → risk decision → order → broker → exit).
 */
export function TradeDetailSheet({ tradeId, onClose }: { tradeId: string | null; onClose: () => void }) {
  const chain = useApi<Chain>(tradeId ? `/trades/${tradeId}` : null);
  const c = chain.data;
  const t = c?.trade;
  const currency = t?.account?.currency;
  return (
    <Sheet open={tradeId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="gap-0 overflow-y-auto data-[side=right]:w-full sm:max-w-lg data-[side=right]:sm:max-w-lg">
        <SheetHeader className="gap-2 border-b border-line p-5 pr-12">
          <SheetTitle className="flex flex-wrap items-center gap-2 text-xl font-extrabold">
            {t ? <>{t.symbol} <Direction trade={t} /></> : "Trade"}
          </SheetTitle>
          <SheetDescription asChild>
            <div className="flex flex-wrap items-center gap-2">
              {t?.account && <EnvBadge env={t.account.environment} />}
              {t && <OutcomeBadge trade={t} />}
              {t && <span>{t.source === "MANUAL" ? "Manual trade" : t.source === "EXTERNAL" ? "Opened outside 2kPilot" : `${t.strategy ?? "Strategy"}${t.strategy_version ? ` v${t.strategy_version}` : ""}`}</span>}
              {t?.is_simulated && <span className="text-fg-subtle">· simulated</span>}
            </div>
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-5 pt-5 pb-8">
          {chain.error && !c ? <ErrorState message={chain.error} onRetry={() => void chain.reload()} /> : !c || !t ? <ListSkeleton rows={4} /> : (
            <>
              <section aria-label="Result" className="rounded-xl bg-surface-raised p-5">
                <p className="eyebrow text-fg-subtle">{t.status === "OPEN" ? "Current P/L (not final)" : "Result"}</p>
                <PnlText value={t.net_pnl ?? t.unrealized_pnl} currency={currency} className="title-xl mt-1 block text-4xl" />
              </section>
              <KeyValue items={[
                ["Contract", tradeContractLabel(t) + (t.contract_type ? ` (${t.contract_type})` : "")],
                ...(t.contract_family === "RISE_FALL" ? [["Duration", durationText(t.duration, t.duration_unit)] as [ReactNode, ReactNode]] : []),
                [t.contract_family && t.contract_family !== "SPOT" ? "Stake" : "Size", sizeText(t, currency)],
                ["Opened", formatDateTime(t.entry_time)],
                ["Entry", formatPrice(t.entry_spot ?? t.entry_price, t.symbol)],
                ...(t.expires_at ? [["Expires", formatDateTime(t.expires_at)] as [ReactNode, ReactNode]] : []),
                ["Closed", t.exit_time ? formatDateTime(t.exit_time) : "Still open"],
                ["Exit", t.exit_time ? formatPrice(t.exit_spot ?? t.exit_price, t.symbol) : "—"],
                ...(t.exit_reason ? [["Why it closed", humanize(t.exit_reason)] as [ReactNode, ReactNode]] : []),
                ["Fees", formatCurrency(t.fees ?? t.commission ?? 0, currency)],
                ...(t.payout ? [["Payout", formatCurrency(t.payout, currency)] as [ReactNode, ReactNode]] : []),
                ["Held for", formatDuration(t.duration_seconds)],
                ...(t.broker_contract_id ? [["Broker contract", <span key="id" className="num text-xs">{t.broker_contract_id}</span>] as [ReactNode, ReactNode]] : []),
              ]} />
              {t.longcode && (
                <section>
                  <h3 className="eyebrow mb-2 text-fg-subtle">What the broker says</h3>
                  <p className="rounded-lg bg-surface-raised p-3.5 text-sm leading-relaxed text-fg-muted">{t.longcode}</p>
                </section>
              )}
              <Accordion type="multiple" defaultValue={["why"]} className="rounded-lg border border-line px-3">
                <AccordionItem value="why">
                  <AccordionTrigger>Why the bot took this trade</AccordionTrigger>
                  <AccordionContent className="space-y-2">
                    {c.evaluation ? (
                      <>
                        <p className="text-sm text-fg">{c.evaluation.summary}</p>
                        <Checks items={c.evaluation.checks.map((x) => ({ rule: x.name, passed: x.passed, detail: x.detail }))} />
                      </>
                    ) : c.signal ? <p className="text-sm text-fg">{c.signal.reasons.join("; ")}</p>
                      : <p className="text-sm text-fg-muted">{t.source === "STRATEGY" ? "The market check was not stored." : "Not opened by a strategy."}</p>}
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="risk">
                  <AccordionTrigger>Risk checks ({c.signal?.risk_checks?.filter((r) => r.passed).length ?? 0}/{c.signal?.risk_checks?.length ?? 0} passed)</AccordionTrigger>
                  <AccordionContent>
                    {c.signal?.risk_checks?.length ? <Checks items={c.signal.risk_checks} /> : <p className="text-sm text-fg-muted">No risk checks stored.</p>}
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="orders">
                  <AccordionTrigger>Orders sent to the broker ({c.orders.length})</AccordionTrigger>
                  <AccordionContent className="space-y-2">
                    {c.orders.length ? c.orders.map((o) => (
                      <div key={o.id} className="rounded-lg border border-line px-3 py-2 text-sm">
                        <p className="text-fg">{o.purpose === "ENTRY" ? "Open" : "Close"} · {humanize(o.status)}</p>
                        <p className="num text-xs text-fg-subtle">fill {o.fill_price ?? "—"}{o.broker_message ? ` · ${o.broker_message}` : ""}</p>
                      </div>
                    )) : <p className="text-sm text-fg-muted">—</p>}
                  </AccordionContent>
                </AccordionItem>
                <AccordionItem value="journal" className="border-b-0">
                  <AccordionTrigger>Timeline ({c.events.length})</AccordionTrigger>
                  <AccordionContent>
                    <ol className="space-y-2 border-l border-line pl-4">
                      {c.events.map((e) => (
                        <li key={e.id} className="text-sm">
                          <span className="num text-xs text-fg-subtle">{formatDateTime(e.occurred_at)}</span>{" "}
                          <span className="text-xs font-medium text-fg-muted">{humanize(e.event_type)}</span>
                          <p className="text-fg">{e.message}</p>
                        </li>
                      ))}
                      {c.events.length === 0 && <li className="text-sm text-fg-muted">No events.</li>}
                    </ol>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function Checks({ items }: { items: RiskCheck[] }) {
  return (
    <ul className="space-y-1">
      {items.map((c, i) => (
        <li key={`${c.rule}-${i}`} className="flex gap-2 text-sm">
          {c.passed
            ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-positive" aria-label="passed" />
            : <CircleX className="mt-0.5 size-4 shrink-0 text-negative" aria-label="failed" />}
          <span><span className="text-fg">{c.rule}</span> <span className="text-fg-subtle">— {c.detail}</span></span>
        </li>
      ))}
    </ul>
  );
}
