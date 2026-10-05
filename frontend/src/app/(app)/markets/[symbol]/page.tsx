import type { Metadata } from "next";
import { InstrumentScreen } from "@/features/markets/InstrumentScreen";

export const metadata: Metadata = { title: "Instrument" };

export default async function InstrumentPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  return <InstrumentScreen symbol={decodeURIComponent(symbol)} />;
}
