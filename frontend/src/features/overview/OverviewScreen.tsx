"use client";

import { useSession } from "@/components/providers/SessionProvider";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { PageHeader } from "@/components/ui/PageHeader";
import { AccountMetrics } from "./AccountMetrics";
import { RecentActivity } from "./RecentActivity";
import { SetupProgress } from "./SetupProgress";
import { StatusAnswers } from "./StatusAnswers";

export function OverviewScreen() {
  const { user, isOwner } = useSession();
  const { status, error } = useSystemStatus();

  return (
    <>
      <PageHeader title="Overview" description={`Welcome back, ${user.display_name}.`} />
      {!status ? (
        <p className="text-sm text-fg-muted">{error ? error.message : "Loading status…"}</p>
      ) : (
        <div className="space-y-6">
          <StatusAnswers status={status} />
          <AccountMetrics connected={status.broker_accounts_connected > 0} />
          <div className="grid gap-6 lg:grid-cols-5">
            <div className="lg:col-span-3">
              <SetupProgress status={status} />
            </div>
            <div className="lg:col-span-2">{isOwner && <RecentActivity />}</div>
          </div>
        </div>
      )}
    </>
  );
}
