"use client";

import { Bell } from "lucide-react";
import { useState } from "react";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/Fields";
import { EmptyState, Loading } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatRelative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AppNotification, Paginated } from "@/lib/types";

const DOT = { info: "bg-info", success: "bg-positive", warning: "bg-warning", critical: "bg-negative" };

export function NotificationsScreen() {
  const { reloadUnread } = useAppData();
  const [filter, setFilter] = useState<"all" | "unread" | "critical">("all");
  const list = useApi<Paginated<AppNotification>>("/notifications", {
    unread: filter === "unread" ? 1 : undefined, severity: filter === "critical" ? "critical" : undefined, per_page: 100,
  }, 10000);
  const markAll = async () => {
    await api("/notifications/read", { method: "POST", body: {} });
    await Promise.all([list.reload(), reloadUnread()]);
  };
  const markOne = async (id: number) => {
    await api("/notifications/read", { method: "POST", body: { ids: [id] } });
    await Promise.all([list.reload(), reloadUnread()]);
  };
  return (
    <div>
      <PageHeader title="Notifications" description="Broker connections, signals, risk decisions, fills, exits and system events."
        actions={<><Segmented size="sm" label="Filter" value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "unread", label: "Unread" }, { value: "critical", label: "Critical" }]} /><Button size="sm" onClick={() => void markAll()}>Mark all read</Button></>} />
      <Card>
        {!list.data ? <Loading /> : list.data.data.length === 0 ? <EmptyState icon={Bell} title="Nothing here" /> : (
          <ul className="divide-y divide-line">
            {list.data.data.map((n) => (
              <li key={n.id} className={cn("flex gap-3 px-5 py-3.5", !n.read_at && "bg-surface-raised/40")}>
                <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", DOT[n.severity])} aria-label={n.severity} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-fg">{n.title}</p>
                  <p className="text-sm text-fg-muted">{n.message}</p>
                  <p className="mt-0.5 text-xs text-fg-subtle">{formatRelative(n.created_at)}</p>
                </div>
                {!n.read_at && <button type="button" onClick={() => void markOne(n.id)} className="self-start text-xs text-accent hover:underline">Mark read</button>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
