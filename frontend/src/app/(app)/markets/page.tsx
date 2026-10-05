import type { Metadata } from "next";
import { MarketsScreen } from "@/features/markets/MarketsScreen";

export const metadata: Metadata = { title: "Markets" };

export default function MarketsPage() {
  return <MarketsScreen />;
}
