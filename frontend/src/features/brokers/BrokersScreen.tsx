"use client";

import { Plus } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import type { Tone } from "@/lib/status";
import type { Connector, ConnectorStatus } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

const STATUS: Record<ConnectorStatus, { label: string; tone: Tone }> = {
  available: { label: "Available", tone: "positive" },
  unavailable: { label: "Not available on this server", tone: "warning" },
  planned: { label: "Planned", tone: "neutral" },
};

export function BrokersScreen() {
  const { data, error, loading } = useApiResource<Connector[]>("/brokers/connectors", { refetchOnFocus: false });
  const anyAvailable = data?.some((c) => c.status === "available") ?? false;

  return (
    <>
      <PageHeader
        title="Brokers"
        description="Trading accounts the robot can connect to. A connection type is only offered once it genuinely works."
        actions={
          <Button variant="primary" disabled={!anyAvailable} title={anyAvailable ? undefined : "No connection type is available yet"}>
            <Plus aria-hidden className="size-4" /> Add broker
          </Button>
        }
      />
      <div className="space-y-6">
        <Card>
          <CardHeader title="Connected accounts" />
          <CardBody>
            <p className="text-sm text-fg-muted">No accounts connected.</p>
            <p className="mt-1 text-xs text-fg-subtle">
              Each account will show its broker, Demo/Live status, balance, equity, margin and which strategies use it.
              Credentials are encrypted at rest and never displayed again after saving.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Connection types" />
          {loading && <CardBody><p className="text-sm text-fg-subtle">Loading…</p></CardBody>}
          {error && <CardBody><p className="text-sm text-negative">{error.message}</p></CardBody>}
          <ul className="divide-y divide-line">
            {data?.map((connector) => (
              <li key={connector.id} className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
                <div className="max-w-2xl">
                  <p className="text-sm font-medium text-fg">{connector.name}</p>
                  <p className="mt-1 text-sm text-fg-muted">{connector.status_detail}</p>
                  <p className="mt-2 text-xs text-fg-subtle">
                    Requires: {connector.fields.map((f) => f.label + (f.secret ? " (encrypted)" : "")).join(" · ")}
                  </p>
                </div>
                <Badge tone={STATUS[connector.status].tone}>{STATUS[connector.status].label}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
