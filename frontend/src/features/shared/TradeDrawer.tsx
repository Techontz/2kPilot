"use client";

import { Check, X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Dialog } from "@/components/ui/Dialog";
import { KeyValue, Loading, Pnl, SideBadge } from "@/components/ui/Misc";
import { cn } from "@/lib/cn";
import { formatMoney, formatPnl, formatPrice, formatTime, humanize } from "@/lib/format";
import type { JournalEvent, OrderRow, RiskCheck, SignalRow, StrategyCheck, Trade } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

interface Lifecycle {
  trade: Trade;
  signal: SignalRow | null;
  evaluation: { outcome: string; summary: string; checks: StrategyCheck[] } | null;
  orders: OrderRow[];
  events: JournalEvent[];
}

function CheckList({ items }: { items: { label: string; passed: boolean; detail: string }[] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((c, i) => (
        <li key={i} className="flex gap-2 text-sm">
          {c.passed ? (
            <Check aria-label="passed" className="mt-0.5 size-4 shrink-0 text-positive" />
          ) : (
            <X aria-label="failed" className="mt-0.5 size-4 shrink-0 text-negative" />
          )}
          <span>
            <span className="text-fg">{c.label}</span> <span className="text-fg-subtle">— {c.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function riskItems(checks: RiskCheck[]) {
  return checks.map((c) => ({ label: c.rule, passed: c.passed, detail: c.detail }));
}

/** Signal → risk decision → orders → position → exit, for one trade. */
export function TradeDrawer({ tradeId, onClose }: { tradeId: string | null; onClose: () => void }) {
  const { data, error } = useApiResource<Lifecycle>(tradeId ? `/trades/${tradeId}` : "/trades/none", {
    enabled: tradeId !== null,
    refetchOnFocus: false,
  });
  const t = data?.trade;
  return (
    <Dialog open={tradeId !== null} onClose={onClose} variant="drawer" title={t ? `${t.side} ${t.volume} ${t.symbol}` : "Trade"}>
      {!data && !error && <Loading />}
      {error && <p className="text-sm text-negative">{error.message}</p>}
      {data && t && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <SideBadge side={t.side} />
            <Badge tone={t.status === "OPEN" ? "info" : "neutral"}>{t.status}</Badge>
            {t.is_simulated && <Badge tone="neutral">PAPER · simulated</Badge>}
            {t.exit_reason && <Badge tone="neutral">{humanize(t.exit_reason)}</Badge>}
            {t.strategy && <span className="text-xs text-fg-subtle">{t.strategy}</span>}
          </div>
          <section>
            <h3 className="mb-2 text-xs font-medium tracking-wide text-fg-subtle uppercase">Result</h3>
            <KeyValue
              items={[
                ["Net P/L", <Pnl key="n" value={t.net_pnl ?? t.unrealized_pnl}>{formatPnl(t.net_pnl ?? t.unrealized_pnl)}</Pnl>],
                ["R multiple", t.r_multiple ?? "—"],
                ["Requested / actual entry", `${formatPrice(t.requested_entry, t.symbol)} / ${formatPrice(t.entry_price, t.symbol)}`],
                ["Slippage", t.slippage_pips !== null ? `${t.slippage_pips} pips` : "—"],
                ["Spread at entry", formatPrice(t.spread_at_entry, t.symbol)],
                ["Stop loss / take profit", `${formatPrice(t.stop_loss, t.symbol)} / ${formatPrice(t.take_profit, t.symbol)}`],
                ["Risked", formatMoney(t.risk_amount)],
                ["Exit", t.exit_price ? `${formatPrice(t.exit_price, t.symbol)} at ${formatTime(t.exit_time)}` : "Open"],
                ["Fees (commission + swap)", `${formatMoney(t.commission)} + ${formatMoney(t.swap)}`],
                ["Session", t.session ?? "—"],
              ]}
            />
          </section>
          {data.signal && (
            <section>
              <h3 className="mb-2 text-xs font-medium tracking-wide text-fg-subtle uppercase">Why the strategy signalled</h3>
              {data.evaluation ? (
                <CheckList items={data.evaluation.checks.map((c) => ({ label: c.name, passed: c.passed, detail: c.detail }))} />
              ) : (
                <ul className="list-disc pl-5 text-sm text-fg-muted">
                  {data.signal.reasons.map((r) => <li key={r}>{r}</li>)}
                </ul>
              )}
            </section>
          )}
          {data.signal && data.signal.risk_checks.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-medium tracking-wide text-fg-subtle uppercase">Risk engine decision</h3>
              <CheckList items={riskItems(data.signal.risk_checks)} />
            </section>
          )}
          <section>
            <h3 className="mb-2 text-xs font-medium tracking-wide text-fg-subtle uppercase">Timeline</h3>
            <ol className="relative space-y-3 border-l border-line pl-4">
              {data.events.map((e) => (
                <li key={e.id} className="text-sm">
                  <span className={cn("absolute -left-[5px] mt-1.5 size-2.5 rounded-full border-2 border-surface",
                    e.event_type.includes("REJECT") || e.event_type.includes("FAIL") ? "bg-negative"
                      : e.event_type.includes("UNKNOWN") ? "bg-warning" : "bg-accent")} />
                  <p className="text-fg">{e.message}</p>
                  <p className="text-xs text-fg-subtle">{humanize(e.event_type)} · {formatTime(e.occurred_at)}</p>
                </li>
              ))}
            </ol>
          </section>
          {data.orders.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-medium tracking-wide text-fg-subtle uppercase">Orders</h3>
              <ul className="space-y-2 text-sm">
                {data.orders.map((o) => (
                  <li key={o.id} className="rounded-lg border border-line px-3 py-2">
                    <div className="flex justify-between gap-2">
                      <span>{o.purpose} · {o.side} {o.volume} · {o.status}</span>
                      <span className="num text-xs text-fg-subtle">{o.client_order_id}</span>
                    </div>
                    {o.broker_message && <p className="mt-1 text-xs text-fg-subtle">{o.broker_message}</p>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </Dialog>
  );
}
