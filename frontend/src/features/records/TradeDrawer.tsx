"use client";

import { CircleCheck, CircleX } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { EnvBadge, KeyValue, Loading, Pnl, SideBadge } from "@/components/ui/Misc";
import { cn } from "@/lib/cn";
import { formatPnl, formatPrice, formatTime, humanize } from "@/lib/format";
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
 * The full decision chain of a trade:
 * market condition → strategy signal → risk decision → order → broker → position → exit → P/L.
 */
export function TradeDrawer({ tradeId, onClose }: { tradeId: string | null; onClose: () => void }) {
  const chain = useApi<Chain>(tradeId ? `/trades/${tradeId}` : null);
  const c = chain.data;
  return (
    <Dialog open={tradeId !== null} onClose={onClose} variant="drawer" title={c ? `${c.trade.side} ${c.trade.symbol}` : "Trade"}>
      {!c ? <Loading /> : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            {c.trade.account && <EnvBadge env={c.trade.account.environment} />}
            <SideBadge side={c.trade.side} />
            <span className="text-sm text-fg-muted">{c.trade.source === "MANUAL" ? "Manual ticket" : c.trade.source === "EXTERNAL" ? "Opened outside 2kFX" : `${c.trade.strategy} v${c.trade.strategy_version}`}</span>
            {c.trade.is_simulated && <span className="text-xs text-fg-subtle">· simulated</span>}
          </div>
          <Step n={1} title="Market condition">
            {c.evaluation ? (
              <>
                <p className="text-sm text-fg">{c.evaluation.summary}</p>
                <Checks items={c.evaluation.checks.map((x) => ({ rule: x.name, passed: x.passed, detail: x.detail }))} />
              </>
            ) : <p className="text-sm text-fg-muted">{c.trade.source === "STRATEGY" ? "Evaluation not stored." : "Not applicable (manual or external)."}</p>}
          </Step>
          <Step n={2} title="Signal">
            {c.signal ? (
              <KeyValue items={[
                ["Reasons", c.signal.reasons.join("; ")],
                ["Entry / stop / target", `${formatPrice(c.signal.entry_price, c.trade.symbol)} / ${formatPrice(c.signal.stop_loss, c.trade.symbol)} / ${formatPrice(c.signal.take_profit, c.trade.symbol)}`],
                ["Created", formatTime(c.signal.created_at)],
              ]} />
            ) : <p className="text-sm text-fg-muted">No signal (position opened outside 2kFX).</p>}
          </Step>
          <Step n={3} title="Risk decision">
            {c.signal?.risk_checks?.length ? <Checks items={c.signal.risk_checks} /> : <p className="text-sm text-fg-muted">—</p>}
          </Step>
          <Step n={4} title="Orders & broker response">
            {c.orders.length ? c.orders.map((o) => (
              <div key={o.id} className="rounded-lg border border-line px-3 py-2 text-sm">
                <p className="text-fg">{o.purpose === "ENTRY" ? "Entry" : "Exit"} · {o.side} {Number(o.volume)} · <span className={cn(o.status === "FILLED" ? "text-positive" : "text-warning")}>{humanize(o.status)}</span></p>
                <p className="num text-xs text-fg-subtle">id {o.client_order_id} · fill {o.fill_price ?? "—"}{o.broker_message ? ` · ${o.broker_message}` : ""}</p>
              </div>
            )) : <p className="text-sm text-fg-muted">—</p>}
          </Step>
          <Step n={5} title="Position, exit and P/L">
            <KeyValue items={[
              ["Opened", `${formatTime(c.trade.entry_time)} at ${formatPrice(c.trade.entry_price, c.trade.symbol)}`],
              ["Closed", c.trade.exit_time ? `${formatTime(c.trade.exit_time)} at ${formatPrice(c.trade.exit_price, c.trade.symbol)} (${humanize(c.trade.exit_reason ?? "")})` : "Still open"],
              ["Risked", formatPnl(c.trade.risk_amount, c.trade.account?.currency).replace("+", "")],
              ["Net P/L", <Pnl key="p" value={c.trade.net_pnl ?? c.trade.unrealized_pnl}>{formatPnl(c.trade.net_pnl ?? c.trade.unrealized_pnl, c.trade.account?.currency)}</Pnl>],
              ["R multiple", c.trade.r_multiple ? `${Number(c.trade.r_multiple).toFixed(2)} R` : "—"],
            ]} />
          </Step>
          <Step n={6} title="Journal">
            <ol className="space-y-2 border-l border-line pl-4">
              {c.events.map((e) => (
                <li key={e.id} className="text-sm">
                  <span className="num text-xs text-fg-subtle">{formatTime(e.occurred_at)}</span> <span className="text-xs font-medium text-fg-muted">{humanize(e.event_type)}</span>
                  <p className="text-fg">{e.message}</p>
                </li>
              ))}
            </ol>
          </Step>
        </div>
      )}
    </Dialog>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
        <span className="num flex size-5 items-center justify-center rounded-full bg-surface-raised text-[11px] text-fg-muted">{n}</span>{title}
      </h3>
      <div className="space-y-2 pl-7">{children}</div>
    </section>
  );
}

export function Checks({ items }: { items: RiskCheck[] }) {
  return (
    <ul className="space-y-1">
      {items.map((c) => (
        <li key={c.rule} className="flex gap-2 text-sm">
          {c.passed ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-positive" aria-label="passed" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-negative" aria-label="failed" />}
          <span><span className="text-fg">{c.rule}</span> <span className="text-fg-subtle">— {c.detail}</span></span>
        </li>
      ))}
    </ul>
  );
}
