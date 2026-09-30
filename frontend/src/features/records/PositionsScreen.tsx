"use client";

import { Wallet } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DataTable } from "@/components/ui/DataTable";
import { Field, TextInput } from "@/components/ui/Fields";
import { EmptyState, Notice, Pnl, SideBadge } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { Term } from "@/components/ui/Term";
import { apiRequest } from "@/lib/api";
import { formatMoney, formatPnl, formatPrice, formatTime } from "@/lib/format";
import type { Trade } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApiResource } from "@/lib/useApiResource";
import { AccountPicker } from "@/features/shared/AccountPicker";
import { TradeDrawer } from "@/features/shared/TradeDrawer";
import { useAccounts } from "@/features/shared/useAccounts";

export function PositionsScreen() {
  const { isOwner } = useSession();
  const acc = useAccounts({ allowAll: true });
  const path = acc.selected ? `/positions?account_id=${acc.selected}` : "/positions";
  const positions = useApiResource<Trade[]>(path);
  useLiveRefresh(["journal", "account"], () => void positions.reload());
  const [closing, setClosing] = useState<Trade | null>(null);
  const [editing, setEditing] = useState<Trade | null>(null);
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [drawer, setDrawer] = useState<string | null>(null);
  const action = useAction();

  const total = (positions.data ?? []).reduce((s, t) => s + Number(t.unrealized_pnl ?? 0), 0);

  return (
    <>
      <PageHeader
        title="Positions"
        description="Trades that are open right now. Stop losses and take profits are held at the broker, so they work even if 2kFX is offline."
        actions={acc.accounts.length > 1 && <AccountPicker accounts={acc.accounts} value={acc.selected} onChange={acc.setSelected} allowAll />}
      />
      {positions.data && positions.data.length > 0 && (
        <p className="mb-4 text-sm text-fg-muted">
          {positions.data.length} open · floating P/L <Pnl value={total}>{formatPnl(total)}</Pnl>
        </p>
      )}
      <Card>
        {positions.data?.length === 0 ? (
          <EmptyState icon={Wallet} title="No open positions">
            When an enabled strategy&apos;s signal passes the risk engine, the resulting position appears here.
          </EmptyState>
        ) : (
          <DataTable
            rows={positions.data}
            loading={positions.loading}
            error={positions.error?.message}
            rowKey={(t) => t.id}
            onRowClick={(t) => setDrawer(t.id)}
            columns={[
              { key: "sym", header: "Symbol", cell: (t) => (
                <span className="flex items-center gap-2 font-medium">{t.symbol}{t.is_simulated && <Badge tone="neutral">PAPER</Badge>}</span>
              ) },
              { key: "side", header: "Side", cell: (t) => <SideBadge side={t.side} /> },
              { key: "vol", header: <Term id="lot">Lots</Term>, align: "right", cell: (t) => t.volume },
              { key: "entry", header: "Entry", align: "right", cell: (t) => formatPrice(t.entry_price, t.symbol) },
              { key: "sl", header: <Term id="stopLoss">SL</Term>, align: "right", hideBelow: "md", cell: (t) => formatPrice(t.stop_loss, t.symbol) },
              { key: "tp", header: <Term id="takeProfit">TP</Term>, align: "right", hideBelow: "md", cell: (t) => formatPrice(t.take_profit, t.symbol) },
              { key: "risk", header: "Risk", align: "right", hideBelow: "lg", cell: (t) => (t.risk_amount ? formatMoney(t.risk_amount) : <span className="text-warning">unknown</span>) },
              { key: "opened", header: "Opened", hideBelow: "lg", cell: (t) => <span className="text-xs text-fg-muted">{formatTime(t.entry_time)}</span> },
              { key: "pnl", header: "P/L", align: "right", cell: (t) => <Pnl value={t.unrealized_pnl}>{formatPnl(t.unrealized_pnl)}</Pnl> },
              ...(isOwner ? [{
                key: "actions", header: <span className="sr-only">Actions</span>, align: "right" as const,
                cell: (t: Trade) => (
                  <span className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                    <Button size="sm" variant="ghost" onClick={() => { setEditing(t); setSl(t.stop_loss ?? ""); setTp(t.take_profit ?? ""); action.setError(null); }}>Edit</Button>
                    <Button size="sm" variant="danger-outline" onClick={() => { setClosing(t); action.setError(null); }}>Close</Button>
                  </span>
                ),
              }] : []),
            ]}
          />
        )}
      </Card>
      <ConfirmDialog
        open={closing !== null}
        title={`Close ${closing?.side} ${closing?.volume} ${closing?.symbol}?`}
        confirmLabel="Close position"
        confirmVariant="danger"
        busy={action.busy}
        error={action.error}
        onCancel={() => setClosing(null)}
        onConfirm={() =>
          void action.run(() => apiRequest(`/positions/${closing?.id}/close`, { method: "POST" })).then((r) => {
            if (r) {
              setClosing(null);
              void positions.reload();
            }
          })
        }
      >
        <p>A market order closes the whole position at the current price. This is recorded in the audit log and journal.</p>
        <p>Current P/L: <Pnl value={closing?.unrealized_pnl}>{formatPnl(closing?.unrealized_pnl)}</Pnl></p>
      </ConfirmDialog>
      <ConfirmDialog
        open={editing !== null}
        title={`Edit ${editing?.symbol} stops`}
        confirmLabel="Save"
        busy={action.busy}
        error={action.error}
        confirmDisabled={!sl}
        onCancel={() => setEditing(null)}
        onConfirm={() =>
          void action.run(() => apiRequest(`/positions/${editing?.id}`, { method: "PUT", body: { stop_loss: sl, take_profit: tp || null } })).then((r) => {
            if (r) {
              setEditing(null);
              void positions.reload();
            }
          })
        }
      >
        <Field label={<Term id="stopLoss" />} hint="Required. A position without a stop loss is never allowed.">
          <TextInput inputMode="decimal" value={sl} onChange={(e) => setSl(e.target.value)} />
        </Field>
        <Field label={<Term id="takeProfit" />} hint="Optional.">
          <TextInput inputMode="decimal" value={tp} onChange={(e) => setTp(e.target.value)} />
        </Field>
        <Notice tone="info">Moving the stop further away increases the money at risk beyond what the risk engine approved.</Notice>
      </ConfirmDialog>
      <TradeDrawer tradeId={drawer} onClose={() => setDrawer(null)} />
    </>
  );
}
