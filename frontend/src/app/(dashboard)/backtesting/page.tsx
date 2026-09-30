import type { Metadata } from "next";
import { Suspense } from "react";
import { BacktestingScreen } from "@/features/backtesting/BacktestingScreen";

export const metadata: Metadata = { title: "Backtesting" };

export default function Page() {
  return (
    <Suspense>
      <BacktestingScreen />
    </Suspense>
  );
}
