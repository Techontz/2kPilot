import type { Metadata } from "next";
import { StrategiesScreen } from "@/features/strategies/StrategiesScreen";

export const metadata: Metadata = { title: "Strategies" };

export default function Page() {
  return <StrategiesScreen />;
}
