import type { Metadata } from "next";
import { Suspense } from "react";
import { NewStrategyScreen } from "@/features/strategies/builder/StrategyBuilderScreens";

export const metadata: Metadata = { title: "New strategy" };

export default function Page() {
  return (
    <Suspense>
      <NewStrategyScreen />
    </Suspense>
  );
}
