import type { Metadata } from "next";
import { HistoryScreen } from "@/features/records/HistoryScreen";

export const metadata: Metadata = { title: "Trade History" };

export default function Page() {
  return <HistoryScreen />;
}
