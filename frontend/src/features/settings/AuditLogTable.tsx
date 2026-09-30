"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { ApiError, apiRequest } from "@/lib/api";
import { describeAuditAction, formatDateTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

const PAGE = 25;

export function AuditLogTable() {
  const first = useApiResource<AuditEntry[]>(`/audit?limit=${PAGE}`, { refetchOnFocus: false });
  const [older, setOlder] = useState<AuditEntry[]>([]);
  const [exhausted, setExhausted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const entries = [...(first.data ?? []), ...older];

  const loadMore = async () => {
    const last = entries.at(-1);
    if (!last) return;
    try {
      const page = await apiRequest<AuditEntry[]>(`/audit?limit=${PAGE}&before_id=${last.id}`);
      setOlder((prev) => [...prev, ...page]);
      if (page.length < PAGE) setExhausted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    }
  };

  return (
    <Card>
      <CardHeader
        title="Audit log"
        description="Every security and trading action. Rows cannot be edited or deleted — the database refuses it."
      />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs text-fg-subtle">
            <tr>
              <th className="px-5 py-2.5 font-medium">Time</th>
              <th className="px-5 py-2.5 font-medium">Action</th>
              <th className="px-5 py-2.5 font-medium">Actor</th>
              <th className="px-5 py-2.5 font-medium">Outcome</th>
              <th className="px-5 py-2.5 font-medium">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {entries.map((e) => (
              <tr key={e.id}>
                <td className="num px-5 py-2.5 whitespace-nowrap text-xs text-fg-muted">{formatDateTime(e.occurred_at)}</td>
                <td className="px-5 py-2.5 text-fg" title={e.action}>
                  {describeAuditAction(e.action)}
                </td>
                <td className="px-5 py-2.5 text-fg-muted">{e.actor_label}</td>
                <td className="px-5 py-2.5">
                  <Badge tone={e.outcome === "success" ? "neutral" : e.outcome === "denied" ? "warning" : "negative"}>
                    {e.outcome}
                  </Badge>
                </td>
                <td className="num px-5 py-2.5 text-xs text-fg-subtle">{e.ip_address ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-line px-5 py-3">
        <span className="text-xs text-fg-subtle">{first.error?.message ?? error ?? `${entries.length} entries shown`}</span>
        {!exhausted && (first.data?.length ?? 0) >= PAGE && (
          <Button size="sm" onClick={() => void loadMore()}>
            Load older
          </Button>
        )}
      </div>
    </Card>
  );
}
