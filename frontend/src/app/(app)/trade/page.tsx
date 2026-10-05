import type { Metadata } from "next";
import { Suspense } from "react";
import { TradeScreen } from "@/features/trade/TradeScreen";

export const metadata: Metadata = { title: "Trade" };

export default function TradePage() {
  return (
    <Suspense>
      <TradeScreen />
    </Suspense>
  );
}
