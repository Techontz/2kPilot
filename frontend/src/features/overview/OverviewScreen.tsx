"use client";

import { useSession } from "@/components/providers/SessionProvider";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { Loading, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import type { Overview } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";
import { EquityPanel } from "./EquityPanel";
import { KeyFigures } from "./KeyFigures";
import { OpenPositions } from "./OpenPositions";
import { RecentActivity } from "./RecentActivity";
import { SetupProgress } from "./SetupProgress";
import { StatusAnswers } from "./StatusAnswers";

export function OverviewScreen() {
  const { user } = useSession();
  const { status, error } = useSystemStatus();
  const overview = useApiResource<Overview>("/overview");
  useLiveRefresh(["journal", "account", "broker"], () => void overview.reload(), 1200);
  const paperOnly = overview.data?.accounts.length && overview.data.accounts.every((a) => a.environment === "PAPER");

  return (
    <>
      <PageHeader title="Overview" description={`Welcome back, ${user.display_name}.`} />
      {!status || !overview.data ? (
        error || overview.error ? <Notice tone="danger">{(error ?? overview.error)?.message}</Notice> : <Loading />
      ) : (
        <div className="space-y-6">
          <StatusAnswers status={status} />
          {paperOnly ? (
            <Notice tone="info" title="Paper / simulation">
              Your only accounts are PAPER accounts: prices and fills are simulated and no money is at risk.
            </Notice>
          ) : null}
          <KeyFigures data={overview.data} />
          <div className="grid gap-6 lg:grid-cols-5">
            <div className="min-w-0 space-y-6 lg:col-span-3">
              <EquityPanel data={overview.data} />
              <OpenPositions />
            </div>
            <div className="min-w-0 space-y-6 lg:col-span-2">
              <RecentActivity events={overview.data.recent_events} />
              <SetupProgress status={status} overview={overview.data} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
