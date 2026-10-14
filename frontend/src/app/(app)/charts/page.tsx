import type { Metadata } from "next";
import { Suspense } from "react";
import { ChartsSection } from "@/features/charts/ChartsSection";

export const metadata: Metadata = { title: "Charts" };

export default function Page() {
  return (
    <Suspense>
      <ChartsSection />
    </Suspense>
  );
}
