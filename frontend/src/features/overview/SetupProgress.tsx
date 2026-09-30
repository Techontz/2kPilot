"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import type { BacktestSummary, Dataset, Overview, StrategyInfo, SystemStatus } from "@/lib/types";
import { useApiResource } from "@/lib/useApiResource";

interface Step {
  title: string;
  detail: string;
  done: boolean;
  href: string;
}

/** The road from install to a first demo trade — every tick is derived from real state. */
export function SetupProgress({ status, overview }: { status: SystemStatus; overview: Overview }) {
  const datasets = useApiResource<Dataset[]>("/market/datasets", { refetchOnFocus: false });
  const strategies = useApiResource<StrategyInfo[]>("/strategies", { refetchOnFocus: false });
  const backtests = useApiResource<BacktestSummary[]>("/backtests?limit=5", { refetchOnFocus: false });
  const assignments = strategies.data?.flatMap((s) => s.assignments) ?? [];
  const steps: Step[] = [
    { title: "Add a trading account", detail: "Paper for simulation, or an MT5 demo account through the Windows bridge.", done: status.broker_accounts_total > 0, href: "/brokers" },
    { title: "Load historical data", detail: "Import a CSV, download from MT5, or generate synthetic data for practice.", done: (datasets.data?.length ?? 0) > 0, href: "/markets" },
    { title: "Backtest the strategy", detail: "Run Trend Pullback V1 on history, then check the out-of-sample result.", done: (backtests.data ?? []).some((b) => b.status === "COMPLETED"), href: "/backtesting" },
    { title: "Assign and enable the strategy", detail: "Choose the account and symbol, give the account a risk profile, then enable.", done: assignments.some((a) => a.status === "ENABLED"), href: "/strategies" },
    { title: "Resume trading on demo/paper", detail: "Release the kill switch. The engine then trades within your risk limits.", done: !status.trading.kill_switch_engaged && status.trading.engine_state !== "offline", href: "/risk" },
    { title: "Review the first trades", detail: "Every decision is in the journal — including rejected signals and why.", done: overview.totals.trades_today > 0 || overview.recent_events.some((e) => e.event_type === "POSITION_OPENED"), href: "/journal" },
  ];
  const completed = steps.filter((s) => s.done).length;
  return (
    <Card>
      <CardHeader title="Path to your first demo trade" description={`${completed} of ${steps.length} complete. Real money is not part of this path.`} />
      <CardBody>
        <ol className="space-y-4">
          {steps.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                step.done ? "border-positive/50 bg-positive-soft text-positive" : "border-line-strong text-fg-subtle")}>
                {step.done ? <Check aria-label="Done" className="size-3.5" /> : index + 1}
              </span>
              <div className="min-w-0">
                <Link href={step.href} className={cn("text-sm font-medium hover:underline", step.done ? "text-fg-muted" : "text-fg")}>{step.title}</Link>
                <p className="mt-0.5 text-sm text-fg-subtle">{step.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}
