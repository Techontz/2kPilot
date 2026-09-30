"use client";

import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { PageHeader } from "@/components/ui/PageHeader";
import { KillSwitchPanel } from "./KillSwitchPanel";
import { PermissionList } from "./PermissionList";
import { RiskLimits } from "./RiskLimits";

export function RiskScreen() {
  const { status, error } = useSystemStatus();
  return (
    <>
      <PageHeader
        title="Risk Management"
        description="The risk engine has the final say over every trade. When in doubt, the safest outcome wins."
      />
      {!status ? (
        <p className="text-sm text-fg-muted">{error ? error.message : "Loading…"}</p>
      ) : (
        <div className="space-y-6">
          <KillSwitchPanel trading={status.trading} />
          <div className="grid gap-6 lg:grid-cols-2">
            <PermissionList trading={status.trading} />
            <RiskLimits />
          </div>
        </div>
      )}
    </>
  );
}
