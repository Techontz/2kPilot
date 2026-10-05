import type { Metadata } from "next";
import { BacktestingScreen } from "@/features/backtesting/BacktestingScreen";

export const metadata: Metadata = { title: "Backtesting" };

export default function Page() {
  return <BacktestingScreen />;
}
