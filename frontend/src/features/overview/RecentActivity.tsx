"use client";

import Link from "next/link";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { formatRelative, humanize } from "@/lib/format";
import type { JournalEvent } from "@/lib/types";
import { cn } from "@/lib/cn";

const DOT: Record<string, string> = {
  RISK_REJECTED: "bg-warning",
  ORDER_REJECTED: "bg-negative",
  ORDER_FAILED: "bg-negative",
  ORDER_UNKNOWN: "bg-warning",
  POSITION_CLOSED: "bg-fg-subtle",
};

export function RecentActivity({ events }: { events: JournalEvent[] }) {
  return (
    <Card>
      <CardHeader
        title="Recent robot activity"
        description="From the trading journal."
        action={<Link href="/journal" className="text-xs text-accent hover:underline">View journal</Link>}
      />
      <CardBody className="py-2">
        {events.length === 0 && <p className="py-3 text-sm text-fg-subtle">No robot activity yet.</p>}
        <ul className="divide-y divide-line">
          {events.map((e) => (
            <li key={e.id} className="flex gap-3 py-2.5">
              <span aria-hidden className={cn("mt-1.5 size-2 shrink-0 rounded-full", DOT[e.event_type] ?? "bg-accent")} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-fg" title={e.message}>{e.message}</p>
                <p className="text-xs text-fg-subtle">{humanize(e.event_type)}</p>
              </div>
              <time dateTime={e.occurred_at} className="shrink-0 text-xs text-fg-subtle">{formatRelative(e.occurred_at)}</time>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
