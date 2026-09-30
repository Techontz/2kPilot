"use client";

import { History } from "lucide-react";
import { useState } from "react";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { TextInput } from "@/components/ui/Fields";
import { EmptyState, Pnl, SideBadge } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard } from "@/components/ui/StatCard";
import { formatPct, formatPnl, formatPrice, formatTime, humanize } from "@/lib/format";
import type { Trade } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { AccountPicker } from "@/features/shared/AccountPicker";
import { TradeDrawer } from "@/features/shared/TradeDrawer";
import { useAccounts } from "@/features/shared/useAccounts";

export function HistoryScreen() {
  const acc = useAccounts({ allowAll: true });
  const [symbol, setSymbol] = useState("");
  const params = new URLSearchParams({ limit: "500" });
  if (acc.selected) params.set("account_id", acc.selected);
  if (symbol.trim()) params.set("symbol", symbol.trim().toUpperCase());
  const trades = useApiResource<Trade[]>(`/trades?${params.toString()}`);
  useLiveRefresh(["journal"], () => void trades.reload());
  const [drawer, setDrawer] = useState<string | null>(null);
  const rows = trades.data ?? [];
  const net = rows.reduce((s, t) => s + Number(t.net_pnl ?? 0), 0);
  const wins = rows.filter((t) => Number(t.net_pnl) > 0).length;

  return (
    <>
      <PageHeader
        title="Trade History"
        description="Every closed trade with requested vs actual prices, costs and why it closed. Click a trade to see its full story."
        actions={
          <div className="flex flex-wrap gap-2">
            {acc.accounts.length > 1 && <AccountPicker accounts={acc.accounts} value={acc.selected} onChange={acc.setSelected} allowAll />}
            <TextInput aria-label="Filter by symbol" placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-32" />
          </div>
        }
      />
      {rows.length > 0 && (
        <div className="mb-6 grid grid-cols-3 gap-3">
          <StatCard label="Closed trades" value={rows.length} />
          <StatCard label="Win rate" value={formatPct((wins / rows.length) * 100, 1)} />
          <StatCard label="Net P/L" value={<Pnl value={net}>{formatPnl(net)}</Pnl>} />
        </div>
      )}
      <Card>
        {trades.data?.length === 0 ? (
          <EmptyState icon={History} title="No closed trades yet">Trades appear here after they close — by stop loss, take profit or manually.</EmptyState>
        ) : (
          <DataTable
            rows={trades.data}
            loading={trades.loading}
            error={trades.error?.message}
            rowKey={(t) => t.id}
            onRowClick={(t) => setDrawer(t.id)}
            columns={[
              { key: "closed", header: "Closed", cell: (t) => <span className="text-xs text-fg-muted">{formatTime(t.exit_time)}</span> },
              { key: "sym", header: "Trade", cell: (t) => (
                <span className="flex items-center gap-2"><SideBadge side={t.side} /><span className="font-medium">{t.volume} {t.symbol}</span>{t.is_simulated && <Badge tone="neutral">PAPER</Badge>}</span>
              ) },
              { key: "strategy", header: "Strategy", hideBelow: "lg", cell: (t) => <span className="text-xs text-fg-muted">{t.strategy ?? "Manual / external"}</span> },
              { key: "entry", header: "Entry → exit", align: "right", hideBelow: "md", cell: (t) => `${formatPrice(t.entry_price, t.symbol)} → ${formatPrice(t.exit_price, t.symbol)}` },
              { key: "reason", header: "Exit", hideBelow: "sm", cell: (t) => <span className="text-xs">{t.exit_reason ? humanize(t.exit_reason) : "—"}</span> },
              { key: "r", header: "R", align: "right", hideBelow: "md", cell: (t) => t.r_multiple ?? "—" },
              { key: "pnl", header: "Net P/L", align: "right", cell: (t) => <Pnl value={t.net_pnl}>{formatPnl(t.net_pnl)}</Pnl> },
            ]}
          />
        )}
      </Card>
      <TradeDrawer tradeId={drawer} onClose={() => setDrawer(null)} />
    </>
  );
}
