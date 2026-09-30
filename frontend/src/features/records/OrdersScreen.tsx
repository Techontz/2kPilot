"use client";

import { ListOrdered } from "lucide-react";
import { useState } from "react";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Select } from "@/components/ui/Fields";
import { EmptyState, SideBadge } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { formatPrice, formatTime, humanize } from "@/lib/format";
import type { Tone } from "@/lib/status";
import type { OrderRow } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { AccountPicker } from "@/features/shared/AccountPicker";
import { useAccounts } from "@/features/shared/useAccounts";

const STATUS_TONE: Record<string, Tone> = {
  FILLED: "positive", PARTIALLY_FILLED: "positive", PENDING: "info", SUBMITTED: "info", PENDING_SUBMIT: "info",
  REJECTED: "negative", FAILED: "negative", CANCELLED: "neutral", UNKNOWN: "warning",
};

export function OrdersScreen() {
  const acc = useAccounts({ allowAll: true });
  const [status, setStatus] = useState("");
  const params = new URLSearchParams();
  if (acc.selected) params.set("account_id", acc.selected);
  if (status) params.set("status", status);
  const orders = useApiResource<OrderRow[]>(`/orders?${params.toString()}`);
  useLiveRefresh(["journal"], () => void orders.reload());
  return (
    <>
      <PageHeader
        title="Orders"
        description="Every instruction sent to a broker, with its idempotency key. UNKNOWN means the outcome is being reconciled — it is never re-sent blindly."
        actions={
          <div className="flex flex-wrap gap-2">
            {acc.accounts.length > 1 && <AccountPicker accounts={acc.accounts} value={acc.selected} onChange={acc.setSelected} allowAll />}
            <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-auto">
              <option value="">All statuses</option>
              {Object.keys(STATUS_TONE).map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </Select>
          </div>
        }
      />
      <Card>
        {orders.data?.length === 0 ? (
          <EmptyState icon={ListOrdered} title="No orders yet">Orders appear once a strategy signal is approved by the risk engine.</EmptyState>
        ) : (
          <DataTable
            rows={orders.data}
            loading={orders.loading}
            error={orders.error?.message}
            rowKey={(o) => o.id}
            columns={[
              { key: "time", header: "Created", cell: (o) => <span className="text-xs text-fg-muted">{formatTime(o.created_at)}</span> },
              { key: "sym", header: "Order", cell: (o) => (
                <span className="flex items-center gap-2">
                  <SideBadge side={o.side} /> <span className="font-medium">{o.volume} {o.symbol}</span>
                  <span className="text-xs text-fg-subtle">{o.purpose === "EXIT" ? "close" : o.order_type.toLowerCase()}</span>
                  {o.is_simulated && <Badge tone="neutral">PAPER</Badge>}
                </span>
              ) },
              { key: "status", header: "Status", cell: (o) => <Badge tone={STATUS_TONE[o.status] ?? "neutral"}>{humanize(o.status)}</Badge> },
              { key: "req", header: "Requested", align: "right", hideBelow: "md", cell: (o) => formatPrice(o.requested_price, o.symbol) },
              { key: "fill", header: "Filled", align: "right", cell: (o) => formatPrice(o.fill_price, o.symbol) },
              { key: "msg", header: "Broker response", hideBelow: "lg", cell: (o) => <span className="text-xs text-fg-muted">{o.broker_message ?? "—"}</span> },
              { key: "id", header: "Client ID", hideBelow: "lg", cell: (o) => <span className="num text-xs text-fg-subtle">{o.client_order_id}</span> },
            ]}
          />
        )}
      </Card>
    </>
  );
}
