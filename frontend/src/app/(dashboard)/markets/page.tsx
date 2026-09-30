import { CandlestickChart } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Markets" };

export default function MarketsPage() {
  return (
    <>
      <PageHeader title="Markets" description="Currency pairs, prices and historical data." />
      <PlannedFeature icon={CandlestickChart} title="Market data" phase="Phase 3" willShow={["Symbols with pip size and lot limits", "Live bid/ask and spread", "Historical candles (M1 to W1)", "Data-quality checks and gaps"]}>
        Symbol details, live quotes and validated historical candles for research and backtesting.
      </PlannedFeature>
    </>
  );
}
