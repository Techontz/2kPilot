import type { Metadata } from "next";
import { HistoryScreen } from "@/features/records/RecordsScreens";

export const metadata: Metadata = { title: "History" };

export default function Page() {
  return <HistoryScreen />;
}
