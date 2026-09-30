import { Check } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import type { SystemStatus } from "@/lib/types";

interface Step {
  title: string;
  detail: string;
  done: boolean;
  available: boolean;
  phase?: string;
}

function steps(status: SystemStatus): Step[] {
  return [
    { title: "Secure owner account", detail: "You are signed in with a protected account.", done: true, available: true },
    {
      title: "Connect an MT5 demo account",
      detail: "Link a broker demo account so the robot can read prices and your balance.",
      done: status.broker_accounts_connected > 0,
      available: false,
      phase: "Phase 2",
    },
    {
      title: "Load historical market data",
      detail: "Download and validate candles for the pairs you want to research.",
      done: false,
      available: false,
      phase: "Phase 3",
    },
    {
      title: "Configure Trend Pullback V1",
      detail: "Set the 4H trend filter, 1H entry rules and risk/reward.",
      done: false,
      available: false,
      phase: "Phase 4",
    },
    {
      title: "Backtest with realistic costs",
      detail: "Prove — or disprove — an edge on in-sample and out-of-sample data.",
      done: false,
      available: false,
      phase: "Phase 6",
    },
    {
      title: "Run on demo",
      detail: "Trade automatically with virtual money, under full risk control.",
      done: false,
      available: false,
      phase: "Phase 7",
    },
  ];
}

/** The road from install to a first demo trade — safety first, profits later. */
export function SetupProgress({ status }: { status: SystemStatus }) {
  const list = steps(status);
  const completed = list.filter((s) => s.done).length;
  return (
    <Card>
      <CardHeader
        title="Path to your first demo trade"
        description={`${completed} of ${list.length} complete. Real money is not part of this path.`}
      />
      <CardBody>
        <ol className="space-y-4">
          {list.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                  step.done ? "border-positive/50 bg-positive-soft text-positive" : "border-line-strong text-fg-subtle",
                )}
              >
                {step.done ? <Check aria-label="Done" className="size-3.5" /> : index + 1}
              </span>
              <div className="min-w-0">
                <p className={cn("text-sm font-medium", step.done ? "text-fg-muted" : "text-fg")}>
                  {step.title}
                  {!step.done && step.phase && (
                    <span className="ml-2 text-xs font-normal text-fg-subtle">{step.phase}</span>
                  )}
                </p>
                <p className="mt-0.5 text-sm text-fg-subtle">{step.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </CardBody>
    </Card>
  );
}
