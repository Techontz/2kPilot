import { ListOrdered } from "lucide-react";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlannedFeature } from "@/components/ui/PlannedFeature";

export const metadata: Metadata = { title: "Orders" };

export default function OrdersPage() {
  return (
    <>
      <PageHeader title="Orders" description="Orders sent to your broker." />
      <PlannedFeature icon={ListOrdered} title="Orders" phase="Phase 7" willShow={["Pending and working orders", "Fills and partial fills", "Rejections with reasons", "Idempotency keys for reconciliation"]}>
        Every order the execution engine submits — pending, filled or rejected — with the broker&apos;s response.
      </PlannedFeature>
    </>
  );
}
