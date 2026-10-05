import type { Metadata } from "next";
import { PositionsScreen } from "@/features/records/RecordsScreens";

export const metadata: Metadata = { title: "Positions" };

export default function Page() {
  return <PositionsScreen />;
}
