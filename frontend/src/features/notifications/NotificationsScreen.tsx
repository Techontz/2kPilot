"use client";

import { AlertTriangle, Bell, CircleCheck, Info, OctagonAlert } from "lucide-react";
import { useState } from "react";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/Fields";
import { EmptyState, Loading } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiRequest } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatRelative } from "@/lib/format";
import type { NotificationItem } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

const ICON = { info: Info, success: CircleCheck, warning: AlertTriangle, critical: OctagonAlert };
const COLOR = { info: "text-info", success: "text-positive", warning: "text-warning", critical: "text-negative" };
type Filter = "all" | "unread" | "critical" | "warning";

export function NotificationsScreen() {
  const [filter, setFilter] = useState<Filter>("all");
  const params = new URLSearchParams({ limit: "100" });
  if (filter === "unread") params.set("unread_only", "true");
  if (filter === "critical" || filter === "warning") params.set("severity", filter);
  const list = useApiResource<{ items: NotificationItem[]; unread: number }>(`/notifications?${params.toString()}`);
  useLiveRefresh(["notification"], () => void list.reload(), 400);

  const markAll = async () => {
    await apiRequest("/notifications/read", { method: "POST", body: { ids: null } });
    void list.reload();
  };
  const markOne = async (id: number) => {
    await apiRequest("/notifications/read", { method: "POST", body: { ids: [id] } });
    void list.reload();
  };

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Alerts about brokers, trades, risk limits and the system. Shown in-app; email or chat channels can be added later."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented label="Filter" value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "unread", label: "Unread" }, { value: "critical", label: "Critical" }, { value: "warning", label: "Warnings" }]} />
            <Button size="sm" disabled={!list.data?.unread} onClick={() => void markAll()}>Mark all read</Button>
          </div>
        }
      />
      <Card>
        {!list.data && <Loading />}
        {list.data?.items.length === 0 && <EmptyState icon={Bell} title="Nothing here">You&apos;re all caught up.</EmptyState>}
        <ul className="divide-y divide-line">
          {list.data?.items.map((n) => {
            const Icon = ICON[n.severity];
            return (
              <li key={n.id} className={cn("flex gap-3 px-5 py-3.5", !n.read_at && "bg-surface-raised/40")}>
                <Icon aria-label={n.severity} className={cn("mt-0.5 size-4 shrink-0", COLOR[n.severity])} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-fg">{n.title}</p>
                  <p className="text-sm text-fg-muted">{n.message}</p>
                  <p className="mt-0.5 text-xs text-fg-subtle">{formatRelative(n.created_at)}</p>
                </div>
                {!n.read_at && <Button size="sm" variant="ghost" onClick={() => void markOne(n.id)}>Mark read</Button>}
              </li>
            );
          })}
        </ul>
      </Card>
    </>
  );
}
