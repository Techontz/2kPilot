import { BookOpen } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Journal" };

export default function JournalPage() {
  return (
    <>
      <PageHeader title="Journal" description="Every decision the robot makes, and why." />
      <PlannedFeature icon={BookOpen} title="Trading journal" phase="Phase 7" willShow={["Executed trades with full context", "Rejected signals with the reason", "Strategy version for each decision", "Correlation IDs to trace any trade"]}>
        Every decision is recorded automatically — including trades the risk engine refused and why.
      </PlannedFeature>
    </>
  );
}
