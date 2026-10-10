"use client";

import { Timer, TrendingDown, TrendingUp } from "lucide-react";
import { Direction, EnvBadge, OutcomeBadge } from "@/components/app/badges";
import { Money, PnlText } from "@/components/app/money";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { directionIsUp, sizeText, tradeContractLabel } from "@/lib/contracts";
import { formatCountdown, formatDuration, formatPrice, formatTime } from "@/lib/format";
import { useNow } from "@/lib/hooks";
import type { Trade } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Trades as a table on wide screens and as cards on phones (no sideways
 * scrolling at 375 px). Rows open the trade detail sheet.
 */
export function TradeList({ trades, open, onSelect, showAccount }: { trades: Trade[]; open?: boolean; onSelect: (id: string) => void; showAccount?: boolean }) {
  const now = useNow(1000, Boolean(open && trades.some((t) => t.expires_at)));
  return (
    <>
      <div className="hidden rounded-lg bg-card px-2 pb-2 shadow-card ring-1 ring-line lg:block">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-10 text-center">#</TableHead>
              <TableHead>{open ? "Opened" : "Opened / closed"}</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Strategy</TableHead>
              <TableHead>Contract</TableHead>
              <TableHead className="text-right">Stake / size</TableHead>
              <TableHead className="text-right">Entry</TableHead>
              {!open && <TableHead className="text-right">Exit</TableHead>}
              {!open && <TableHead className="text-right">Fees</TableHead>}
              {!open && <TableHead className="text-right">Payout</TableHead>}
              {open && <TableHead className="text-right">Time left</TableHead>}
              <TableHead className="text-right">{open ? "Current P/L" : "P/L"}</TableHead>
              <TableHead>{open ? "Status" : "Result"}</TableHead>
              {!open && <TableHead className="text-right">Duration</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {trades.map((t, i) => {
              const currency = t.account?.currency;
              const left = t.contract_family === "RISE_FALL" ? formatCountdown(t.expires_at, now) : null;
              return (
                <TableRow key={t.id} className="group cursor-pointer border-0 [&>td:first-child]:rounded-l-md [&>td:last-child]:rounded-r-md" onClick={() => onSelect(t.id)}>
                  <TableCell className="num w-10 text-center text-fg-subtle group-hover:text-fg">{i + 1}</TableCell>
                  <TableCell className="text-xs text-fg-muted">
                    <button type="button" className="text-left hover:text-fg focus-visible:underline" onClick={(e) => { e.stopPropagation(); onSelect(t.id); }}
                      aria-label={`Details of ${t.symbol} trade opened ${formatTime(t.entry_time)}`}>
                      <span className="block">{formatTime(t.entry_time)}</span>
                      {!open && <span className="block text-fg-subtle">{formatTime(t.exit_time)}</span>}
                    </button>
                  </TableCell>
                  <TableCell>
                    <span className="font-bold text-fg">{t.symbol}</span>
                    {showAccount && t.account && <span className="mt-0.5 flex items-center gap-1 text-xs text-fg-subtle">{t.account.label} <EnvBadge env={t.account.environment} /></span>}
                  </TableCell>
                  <TableCell className="max-w-40 truncate text-fg-muted">{t.strategy ?? (t.source === "MANUAL" ? "Manual" : "—")}</TableCell>
                  <TableCell><span className="text-fg-muted">{tradeContractLabel(t)}</span> <Direction trade={t} className="ml-1" /></TableCell>
                  <TableCell className="num text-right">{sizeText(t, currency)}</TableCell>
                  <TableCell className="num text-right text-fg-muted">{formatPrice(t.entry_spot ?? t.entry_price, t.symbol)}</TableCell>
                  {!open && <TableCell className="num text-right text-fg-muted">{formatPrice(t.exit_spot ?? t.exit_price, t.symbol)}</TableCell>}
                  {!open && <TableCell className="text-right text-fg-muted"><Money value={t.fees ?? t.commission ?? 0} currency={currency} /></TableCell>}
                  {!open && <TableCell className="text-right text-fg-muted">{t.payout ? <Money value={t.payout} currency={currency} /> : "—"}</TableCell>}
                  {open && <TableCell className="num text-right text-fg-muted">{left ?? "—"}</TableCell>}
                  <TableCell className="text-right font-bold"><PnlText value={open ? t.unrealized_pnl : t.net_pnl} currency={currency} /></TableCell>
                  <TableCell><OutcomeBadge trade={t} /></TableCell>
                  {!open && <TableCell className="num text-right text-xs text-fg-muted">{formatDuration(t.duration_seconds)}</TableCell>}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <ul className="-mx-1 space-y-1 lg:hidden">
        {trades.map((t) => {
          const currency = t.account?.currency;
          const left = t.contract_family === "RISE_FALL" ? formatCountdown(t.expires_at, now) : null;
          return (
            <li key={t.id}>
              <button type="button" onClick={() => onSelect(t.id)}
                className="flex w-full gap-3 rounded-lg p-3 text-left transition-colors hover:bg-surface-hover focus-visible:bg-surface-hover active:bg-surface-hover">
                <DirectionTile trade={t} />
                <span className="min-w-0 flex-1">
                <span className="flex items-start justify-between gap-3">
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-bold text-fg">{t.symbol}</span>
                      <Direction trade={t} />
                      <OutcomeBadge trade={t} />
                    </span>
                    <span className="mt-1 block truncate text-xs text-fg-muted">{tradeContractLabel(t)} · {t.strategy ?? (t.source === "MANUAL" ? "Manual" : "—")}</span>
                  </span>
                  <PnlText value={open ? t.unrealized_pnl : t.net_pnl} currency={currency} className="shrink-0 text-base font-extrabold" />
                </span>
                <span className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-fg-muted">
                  <span>Stake / size <span className="num text-fg">{sizeText(t, currency)}</span></span>
                  <span className={cn(!open && "text-right")}>{open ? <>Opened {formatTime(t.entry_time)}</> : <>Held {formatDuration(t.duration_seconds)}</>}</span>
                  {open ? (
                    left !== null && <span className="num flex items-center gap-1"><Timer className="size-3" aria-hidden /> {left} left</span>
                  ) : (
                    <>
                      <span>Closed {formatTime(t.exit_time)}</span>
                      <span className="text-right">Fees <Money value={t.fees ?? t.commission ?? 0} currency={currency} className="text-fg" /></span>
                    </>
                  )}
                  {showAccount && t.account && <span className="col-span-2 flex items-center gap-1">{t.account.label} <EnvBadge env={t.account.environment} /></span>}
                </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

/** Square "cover" for a trade row: direction at a glance (the text label carries the meaning too). */
function DirectionTile({ trade }: { trade: Trade }) {
  const up = directionIsUp(trade);
  return (
    <span aria-hidden className={cn("flex size-11 shrink-0 items-center justify-center rounded-md", up ? "bg-positive-soft text-positive" : "bg-negative-soft text-negative")}>
      {up ? <TrendingUp className="size-5" /> : <TrendingDown className="size-5" />}
    </span>
  );
}
