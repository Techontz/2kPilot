import type { Metadata } from "next";
import { AnalyticsScreen } from "@/features/analytics/AnalyticsScreen";

export const metadata: Metadata = { title: "Analytics" };

export default function Page() {
  return <AnalyticsScreen />;
}
