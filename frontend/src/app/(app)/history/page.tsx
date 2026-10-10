import type { Metadata } from "next";
import { Suspense } from "react";
import { HistorySection } from "@/features/history/HistorySection";

export const metadata: Metadata = { title: "History" };

export default function Page() {
  return (
    <Suspense>
      <HistorySection />
    </Suspense>
  );
}
