import type { Metadata } from "next";
import { BrokersScreen } from "@/features/brokers/BrokersScreen";

export const metadata: Metadata = { title: "Brokers" };

export default function BrokersPage() {
  return <BrokersScreen />;
}
