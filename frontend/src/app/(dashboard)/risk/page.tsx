import type { Metadata } from "next";
import { RiskScreen } from "@/features/risk/RiskScreen";

export const metadata: Metadata = { title: "Risk Management" };

export default function RiskPage() {
  return <RiskScreen />;
}
