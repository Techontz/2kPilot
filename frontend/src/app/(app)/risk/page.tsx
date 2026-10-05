import type { Metadata } from "next";
import { RiskScreen } from "@/features/risk/RiskScreen";

export const metadata: Metadata = { title: "Risk" };

export default function Page() {
  return <RiskScreen />;
}
