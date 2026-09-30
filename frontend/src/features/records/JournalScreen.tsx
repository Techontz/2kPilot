"use client";

import { BookOpen } from "lucide-react";
import { useState } from "react";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Fields";
import { EmptyState, Loading } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiRequest } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatTime, humanize } from "@/lib/format";
import type { JournalEvent } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { AccountPicker } from "@/features/shared/AccountPicker";
import { TradeDrawer } from "@/features/shared/TradeDrawer";
import { useAccounts } from "@/features/shared/useAccounts";

const TYPES = [
  "SIGNAL_GENERATED", "RISK_APPROVED", "RISK_REJECTED", "ORDER_SUBMITTED", "ORDER_FILLED", "ORDER_REJECTED",
  "ORDER_FAILED", "ORDER_UNKNOWN", "ORDER_RECONCILED", "POSITION_OPENED", "POSITION_MODIFIED", "POSITION_CLOSED",
  "EXTERNAL_POSITION", "ACCOUNT_HALTED",
];

function tone(type: string) {
  if (type.includes("REJECT") || type.includes("FAIL") || type === "ACCOUNT_HALTED") return "bg-negative";
  if (type.includes("UNKNOWN") || type === "EXTERNAL_POSITION") return "bg-warning";
  if (type === "POSITION_OPENED" || type === "ORDER_FILLED") return "bg-positive";
  return "bg-accent";
}

export function JournalScreen() {
  const acc = useAccounts({ allowAll: true });
  const [type, setType] = useState("");
  const [older, setOlder] = useState<JournalEvent[]>([]);
  const [drawer, setDrawer] = useState<string | null>(null);
  const params = new URLSearchParams({ limit: "100" });
  if (acc.selected) params.set("account_id", acc.selected);
  if (type) params.set("event_type", type);
  const query = params.toString();
  const events = useApiResource<JournalEvent[]>(`/journal?${query}`);
  useLiveRefresh(["journal"], () => void events.reload());
  const rows = [...(events.data ?? []), ...older];

  const loadOlder = async () => {
    const last = rows.at(-1);
    if (!last) return;
    const page = await apiRequest<JournalEvent[]>(`/journal?${query}&before_id=${last.id}`);
    setOlder((prev) => [...prev, ...page]);
  };

  return (
    <>
      <PageHeader
        title="Journal"
        description="The robot's complete decision log: every signal, every risk decision (including rejections and why), every order and every exit."
        actions={
          <div className="flex flex-wrap gap-2">
            {acc.accounts.length > 1 && <AccountPicker accounts={acc.accounts} value={acc.selected} onChange={(v) => { acc.setSelected(v); setOlder([]); }} allowAll />}
            <Select aria-label="Event type" value={type} onChange={(e) => { setType(e.target.value); setOlder([]); }} className="w-auto">
              <option value="">All events</option>
              {TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
            </Select>
          </div>
        }
      />
      <Card>
        {!events.data && <Loading />}
        {events.data && rows.length === 0 && (
          <EmptyState icon={BookOpen} title="Nothing recorded yet">Once a strategy is enabled, every decision it makes is written here automatically.</EmptyState>
        )}
        <ol className="divide-y divide-line">
          {rows.map((e) => (
            <li key={e.id}>
              <button
                type="button"
                disabled={!e.trade_id}
                onClick={() => e.trade_id && setDrawer(e.trade_id)}
                className={cn("flex w-full gap-3 px-5 py-3 text-left", e.trade_id && "hover:bg-surface-raised/60")}
              >
                <span aria-hidden className={cn("mt-1.5 size-2 shrink-0 rounded-full", tone(e.event_type))} />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-fg">{e.message}</span>
                  <span className="block text-xs text-fg-subtle">
                    {humanize(e.event_type)}{e.correlation_id && <> · trace {e.correlation_id.slice(0, 8)}</>}
                  </span>
                </span>
                <time dateTime={e.occurred_at} className="shrink-0 text-xs text-fg-subtle">{formatTime(e.occurred_at)}</time>
              </button>
            </li>
          ))}
        </ol>
        {rows.length >= 100 && (
          <div className="border-t border-line px-5 py-3 text-right">
            <Button size="sm" onClick={() => void loadOlder()}>Load older</Button>
          </div>
        )}
      </Card>
      <TradeDrawer tradeId={drawer} onClose={() => setDrawer(null)} />
    </>
  );
}
