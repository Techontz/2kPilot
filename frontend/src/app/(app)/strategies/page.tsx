import type { Metadata } from "next";
import { Suspense } from "react";
import { StrategiesSection } from "@/features/strategies/StrategiesSection";

export const metadata: Metadata = { title: "Strategies" };

export default function Page() {
  return (
    <Suspense>
      <StrategiesSection />
    </Suspense>
  );
}
