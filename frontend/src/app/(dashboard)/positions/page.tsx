import { Wallet } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Positions" };

export default function PositionsPage() {
  return (
    <>
      <PageHeader title="Positions" description="Trades that are currently open." />
      <PlannedFeature icon={Wallet} title="Open positions" phase="Phase 7" willShow={["Symbol, direction and size", "Entry, stop loss and take profit", "Live P/L and open risk", "Strategy that opened it"]}>
        Positions appear here once a broker account is connected and the robot is trading on demo.
      </PlannedFeature>
    </>
  );
}
