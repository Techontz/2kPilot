"use client";

import Link from "next/link";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Pnl, SideBadge } from "@/components/ui/Misc";
import { formatPnl, formatPrice } from "@/lib/format";
import type { Trade } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { useLiveRefresh } from "@/components/providers/StreamProvider";

export function OpenPositions() {
  const { data, error, loading, reload } = useApiResource<Trade[]>("/positions");
  useLiveRefresh(["journal", "account"], () => void reload());
  return (
    <Card>
      <CardHeader
        title="Open positions"
        action={<Link href="/positions" className="text-xs text-accent hover:underline">Manage</Link>}
      />
      <DataTable
        rows={data ? data.slice(0, 6) : null}
        loading={loading}
        error={error?.message}
        rowKey={(t) => t.id}
        empty="No open positions."
        columns={[
          { key: "sym", header: "Symbol", cell: (t) => <span className="font-medium">{t.symbol}</span> },
          { key: "side", header: "Side", cell: (t) => <SideBadge side={t.side} /> },
          { key: "vol", header: "Lots", align: "right", cell: (t) => t.volume },
          { key: "entry", header: "Entry", align: "right", hideBelow: "sm", cell: (t) => formatPrice(t.entry_price, t.symbol) },
          { key: "pnl", header: "P/L", align: "right", cell: (t) => <Pnl value={t.unrealized_pnl}>{formatPnl(t.unrealized_pnl)}</Pnl> },
        ]}
      />
    </Card>
  );
}
