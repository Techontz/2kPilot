"use client";

import { DataTable } from "@/components/ui/DataTable";
import { Pnl, SideBadge } from "@/components/ui/Misc";
import { formatPnl, formatPrice, formatTime, humanize } from "@/lib/format";
import type { TradeRow } from "@/lib/types";

const volume = (v: string) => Number(v).toString();

/** Open positions in compact form (Overview). */
export function PositionsMini({ rows, currency }: { rows: TradeRow[]; currency: string }) {
  return (
    <DataTable
      caption="Open positions"
      rows={rows}
      rowKey={(r) => r.id}
      empty="No open positions."
      columns={[
        { key: "symbol", header: "Symbol", cell: (r) => <span className="font-medium">{r.symbol}</span> },
        { key: "side", header: "Side", cell: (r) => <SideBadge side={r.side} /> },
        { key: "volume", header: "Volume", align: "right", cell: (r) => volume(r.volume) },
        { key: "entry", header: "Entry", align: "right", hideBelow: "sm", cell: (r) => formatPrice(r.entry_price, r.symbol) },
        { key: "sl", header: "Stop", align: "right", hideBelow: "md", cell: (r) => formatPrice(r.stop_loss, r.symbol) },
        { key: "pnl", header: "P/L", align: "right", cell: (r) => <Pnl value={r.unrealized_pnl}>{formatPnl(r.unrealized_pnl, currency)}</Pnl> },
      ]}
    />
  );
}

/** Recently closed trades (Overview). */
export function RecentTradesMini({ rows, currency }: { rows: TradeRow[]; currency: string }) {
  return (
    <DataTable
      caption="Recent trades"
      rows={rows}
      rowKey={(r) => r.id}
      empty="No closed trades yet."
      columns={[
        { key: "time", header: "Closed", cell: (r) => <span className="text-fg-muted">{formatTime(r.exit_time)}</span> },
        { key: "symbol", header: "Symbol", cell: (r) => <span className="font-medium">{r.symbol}</span> },
        { key: "side", header: "Side", cell: (r) => <SideBadge side={r.side} /> },
        { key: "reason", header: "Exit", hideBelow: "sm", cell: (r) => <span className="text-fg-muted">{r.exit_reason ? humanize(r.exit_reason) : "—"}</span> },
        { key: "pnl", header: "Net P/L", align: "right", cell: (r) => <Pnl value={r.net_pnl}>{formatPnl(r.net_pnl, currency)}</Pnl> },
      ]}
    />
  );
}
