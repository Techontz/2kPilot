"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { describeAuditAction, formatRelative } from "@/lib/format";
import type { Tone } from "@/lib/status";
import type { AuditEntry } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

const OUTCOME_TONE: Record<AuditEntry["outcome"], Tone> = {
  success: "neutral",
  failure: "negative",
  denied: "warning",
};

export function RecentActivity() {
  const { data, error, loading } = useApiResource<AuditEntry[]>("/audit?limit=8");
  return (
    <Card>
      <CardHeader
        title="Recent activity"
        description="From the tamper-resistant audit log."
        action={
          <Link href="/settings#audit" className="text-xs text-accent hover:underline">
            View all
          </Link>
        }
      />
      <CardBody className="py-2">
        {loading && <p className="py-3 text-sm text-fg-subtle">Loading…</p>}
        {error && <p className="py-3 text-sm text-negative">{error.message}</p>}
        {data?.length === 0 && <p className="py-3 text-sm text-fg-subtle">No activity yet.</p>}
        <ul className="divide-y divide-line">
          {data?.map((entry) => (
            <li key={entry.id} className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-sm text-fg">{describeAuditAction(entry.action)}</p>
                <p className="truncate text-xs text-fg-subtle">{entry.actor_label}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {entry.outcome !== "success" && <Badge tone={OUTCOME_TONE[entry.outcome]}>{entry.outcome}</Badge>}
                <time dateTime={entry.occurred_at} className="text-xs text-fg-subtle">
                  {formatRelative(entry.occurred_at)}
                </time>
              </div>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
