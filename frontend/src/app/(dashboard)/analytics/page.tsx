import { BarChart3 } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Analytics" };

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader title="Analytics" description="How the robot is performing, measured honestly." />
      <PlannedFeature icon={BarChart3} title="Performance analytics" phase="Phase 8" willShow={["Equity and drawdown curves", "Win rate, profit factor, expectancy", "Performance by pair and session", "Execution quality (slippage)"]}>
        Charts that answer real questions: is the strategy making money after costs, and how deep are the losing streaks?
      </PlannedFeature>
    </>
  );
}
