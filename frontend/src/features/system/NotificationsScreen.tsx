"use client";

import { Bell, CheckCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Pill, type Tone } from "@/components/app/badges";
import { EmptyState, ErrorState, ListSkeleton, SectionHeader } from "@/components/app/states";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AppNotification, Paginated, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = "all" | "unread" | "critical";

const SEVERITY: Record<Severity, { tone: Tone; label: string; dot: string }> = {
  info: { tone: "info", label: "Info", dot: "bg-info" },
  success: { tone: "positive", label: "Done", dot: "bg-positive" },
  warning: { tone: "warning", label: "Warning", dot: "bg-warning" },
  critical: { tone: "negative", label: "Important", dot: "bg-negative" },
};

const EMPTY: Record<Filter, { title: string; text: string }> = {
  all: { title: "No notifications yet", text: "Broker connections, trades, risk decisions and system events will show up here." },
  unread: { title: "You're all caught up", text: "Every notification has been read." },
  critical: { title: "Nothing important", text: "Important alerts — a broker that dropped, a halted platform — appear here." },
};

/** Settings → Notifications: everything the robot and the platform told you. */
export function NotificationsScreen() {
  const { reloadUnread } = useAppData();
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<number | "all" | null>(null);
  const list = useApi<Paginated<AppNotification>>("/notifications", {
    unread: filter === "unread" ? 1 : undefined,
    severity: filter === "critical" ? "critical" : undefined,
    per_page: 100,
  }, 15_000);

  const mark = async (ids?: number[]) => {
    setBusy(ids ? ids[0]! : "all");
    try {
      await api("/notifications/read", { method: "POST", body: ids ? { ids } : {} });
      if (!ids) toast.success("All notifications marked as read");
      await Promise.all([list.reload(), reloadUnread()]);
    } catch (e) {
      toast.error("Could not mark as read", { description: e instanceof ApiError ? e.message : "Try again." });
    } finally {
      setBusy(null);
    }
  };

  const items = list.data?.data ?? null;
  const hasUnread = items?.some((n) => !n.read_at) ?? false;

  return (
    <div>
      <SectionHeader
        title="Notifications"
        description="Broker connections, signals, risk decisions, fills, exits and system events."
        actions={
          <Button size="sm" variant="outline" onClick={() => void mark()} disabled={busy !== null || !hasUnread}>
            <CheckCheck aria-hidden /> Mark all read
          </Button>
        }
      />
      <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)} className="mb-4">
        <TabsList aria-label="Filter notifications">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="unread">Unread</TabsTrigger>
          <TabsTrigger value="critical">Important</TabsTrigger>
        </TabsList>
      </Tabs>
      <Card className="gap-0 py-0">
        {list.error && !items ? (
          <div className="p-4"><ErrorState message={list.error} onRetry={() => void list.reload()} /></div>
        ) : !items ? (
          <div className="p-4"><ListSkeleton rows={5} /></div>
        ) : items.length === 0 ? (
          <EmptyState icon={Bell} title={EMPTY[filter].title}>{EMPTY[filter].text}</EmptyState>
        ) : (
          <ul className="divide-y divide-line" aria-live="polite">
            {items.map((n) => {
              const sev = SEVERITY[n.severity] ?? SEVERITY.info;
              return (
                <li key={n.id} className={cn("flex gap-3 px-4 py-3.5", !n.read_at && "bg-muted/40")}>
                  <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : sev.dot)} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className={cn("text-sm text-fg", !n.read_at && "font-semibold")}>{n.title}</p>
                      {n.severity !== "info" && <Pill tone={sev.tone}>{sev.label}</Pill>}
                      {!n.read_at && <span className="sr-only">(unread)</span>}
                    </div>
                    <p className="mt-0.5 text-sm break-words text-fg-muted">{n.message}</p>
                    <p className="mt-1 text-xs text-fg-subtle"><time dateTime={n.created_at} title={formatDateTime(n.created_at)}>{formatRelative(n.created_at)}</time></p>
                  </div>
                  {!n.read_at && (
                    <Button size="xs" variant="ghost" className="self-start" disabled={busy !== null} onClick={() => void mark([n.id])}
                      aria-label={`Mark “${n.title}” as read`}>
                      Mark read
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      {list.data && list.data.total > list.data.data.length && (
        <p className="mt-3 text-xs text-fg-subtle">Showing the latest {list.data.data.length} of {list.data.total}.</p>
      )}
    </div>
  );
}
