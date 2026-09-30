"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { useApiResource } from "@/lib/useApiResource";

export function NotificationBell() {
  const { data, reload } = useApiResource<{ unread: number }>("/notifications/unread-count");
  useLiveRefresh(["notification", "notification_read"], () => void reload(), 300);
  const unread = data?.unread ?? 0;
  return (
    <Link href="/notifications" className="relative rounded-md p-1.5 text-fg-muted hover:bg-surface-raised hover:text-fg" aria-label={`Notifications, ${unread} unread`}>
      <Bell className="size-4" aria-hidden />
      {unread > 0 && (
        <span className="num absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-canvas">
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}
