"use client";

import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { deriveRobotStatus } from "@/lib/status";
import { ModeSelector } from "./ModeSelector";

export function TradingScreen() {
  const { status, error } = useSystemStatus();
  if (!status) return <p className="text-sm text-fg-muted">{error ? error.message : "Loading…"}</p>;
  const robot = deriveRobotStatus(status.trading);

  return (
    <>
      <PageHeader
        title="Trading"
        description="Control where the robot is allowed to trade. Strategies must also be enabled individually."
      />
      <div className="space-y-6">
        <ModeSelector trading={status.trading} />
        <Card>
          <CardHeader title="Automation engine" action={<Badge tone={robot.tone} dot>{robot.label}</Badge>} />
          <CardBody>
            <p className="text-sm text-fg-muted">{status.trading.engine_detail}</p>
            <p className="mt-3 text-xs text-fg-subtle">
              Pipeline once built: market data → strategy signal → risk engine → execution engine → broker.
              A strategy can only propose a trade; the risk engine decides.
            </p>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
