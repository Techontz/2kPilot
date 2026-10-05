import type { Metadata } from "next";
import { BacktestReport } from "@/features/backtesting/BacktestReport";

export const metadata: Metadata = { title: "Backtest" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <BacktestReport id={id} />;
}
