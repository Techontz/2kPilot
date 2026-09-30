import { History } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Trade History" };

export default function HistoryPage() {
  return (
    <>
      <PageHeader title="Trade History" description="Every trade that has been closed." />
      <PlannedFeature icon={History} title="Closed trades" phase="Phase 7" willShow={["Entry and exit prices", "Spread, commission and swap", "Realised P/L", "Exit reason (stop, target, manual)"]}>
        A complete record of every closed trade with requested vs actual prices, costs and exit reason.
      </PlannedFeature>
    </>
  );
}
