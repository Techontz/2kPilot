import type { Metadata } from "next";
import { TradingScreen } from "@/features/trading/TradingScreen";

export const metadata: Metadata = { title: "Trading" };

export default function TradingPage() {
  return <TradingScreen />;
}
