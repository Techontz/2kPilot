import { FlaskConical } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Backtesting" };

export default function BacktestingPage() {
  return (
    <>
      <PageHeader title="Backtesting" description="Prove whether a strategy has an edge before risking money." />
      <PlannedFeature icon={FlaskConical} title="Backtesting" phase="Phase 6" willShow={["Equity curve and drawdown", "Win rate, expectancy, profit factor", "Monthly and per-session results", "Full simulated trade list"]}>
        Test a strategy on history with realistic spread, commission and slippage — with in-sample / out-of-sample splits so overfitting is visible.
      </PlannedFeature>
    </>
  );
}
