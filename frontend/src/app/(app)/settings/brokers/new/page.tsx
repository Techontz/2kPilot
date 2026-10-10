import type { Metadata } from "next";
import { Suspense } from "react";
import { AddBrokerWizard } from "@/features/brokers/AddBrokerWizard";

export const metadata: Metadata = { title: "Add broker" };

export default function AddBrokerPage() {
  return (
    <Suspense>
      <AddBrokerWizard />
    </Suspense>
  );
}
