import { SlidersHorizontal } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Strategies" };

export default function StrategiesPage() {
  return (
    <>
      <PageHeader title="Strategies" description="Trading strategies and their configuration." />
      <PlannedFeature icon={SlidersHorizontal} title="Strategies" phase="Phase 4" willShow={["Name, version and status", "Markets and timeframes", "Parameters and risk settings", "Last signal and backtest status"]}>
        The first strategy will be Trend Pullback V1: a 4H trend filter with 1H pullback entries. Strategies only propose trades; they must be deliberately enabled, and the risk engine decides.
      </PlannedFeature>
    </>
  );
}
