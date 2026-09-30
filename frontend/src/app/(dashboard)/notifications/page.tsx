import { Bell } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Notifications" };

export default function NotificationsPage() {
  return (
    <>
      <PageHeader title="Notifications" description="Alerts about your accounts and the robot." />
      <PlannedFeature icon={Bell} title="Notifications" phase="Phase 7" willShow={["Broker connection changes", "Trades executed or rejected", "Risk limits reached", "System errors"]}>
        Alerts for broker disconnects, executed and rejected orders, risk limits reached and system errors. In-app first; more channels later.
      </PlannedFeature>
    </>
  );
}
