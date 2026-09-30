"use client";

import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { Loading, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { AccountPicker } from "@/features/shared/AccountPicker";
import { useAccounts } from "@/features/shared/useAccounts";
import { AccountUsage } from "./AccountUsage";
import { EmergencyStop } from "./EmergencyStop";
import { KillSwitchPanel } from "./KillSwitchPanel";
import { PermissionList } from "./PermissionList";
import { ProfileEditor } from "./ProfileEditor";

export function RiskScreen() {
  const { status, error } = useSystemStatus();
  const acc = useAccounts();
  return (
    <>
      <PageHeader
        title="Risk Management"
        description="The risk engine has the final say over every trade. When in doubt, the safest outcome wins."
        actions={acc.accounts.length > 1 && <AccountPicker accounts={acc.accounts} value={acc.selected} onChange={acc.setSelected} />}
      />
      {!status ? (
        error ? <Notice tone="danger">{error.message}</Notice> : <Loading />
      ) : (
        <div className="space-y-6">
          <KillSwitchPanel trading={status.trading} />
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="min-w-0 space-y-6">
              {acc.current ? <AccountUsage account={acc.current} /> : acc.data && <Notice tone="info">Add an account on the Brokers page to see live limit usage.</Notice>}
              <PermissionList trading={status.trading} />
              <EmergencyStop />
            </div>
            <ProfileEditor />
          </div>
        </div>
      )}
    </>
  );
}
