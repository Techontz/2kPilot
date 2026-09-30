import type { Metadata } from "next";
import { JournalScreen } from "@/features/records/JournalScreen";

export const metadata: Metadata = { title: "Journal" };

export default function Page() {
  return <JournalScreen />;
}
