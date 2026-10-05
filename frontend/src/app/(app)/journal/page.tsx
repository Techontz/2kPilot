import type { Metadata } from "next";
import { JournalScreen } from "@/features/records/RecordsScreens";

export const metadata: Metadata = { title: "Journal" };

export default function Page() {
  return <JournalScreen />;
}
