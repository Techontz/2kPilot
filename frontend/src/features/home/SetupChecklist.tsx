"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { SetupChecklist as Setup } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface ChecklistStep {
  key: string;
  title: string;
  detail: string;
  done: boolean;
  action: ReactNode;
}

/** The four first-run steps, in order. The first unfinished one is "current". */
export function checklistSteps(setup: Setup, startAction: ReactNode): ChecklistStep[] {
  return [
    {
      key: "connect",
      title: "Connect Deriv or start Paper",
      detail: "Paper practises with simulated money and needs no sign-up. A Deriv demo account uses real prices with virtual money.",
      done: setup.has_account,
      action: <Button asChild size="sm"><Link href="/settings/brokers/new">Add an account</Link></Button>,
    },
    {
      key: "strategy",
      title: "Pick a strategy",
      detail: "Start from a ready-made template, build your own with simple rules, or describe it in your words.",
      done: setup.has_strategy,
      action: <Button asChild size="sm"><Link href="/strategies?tab=templates">Browse templates</Link></Button>,
    },
    {
      key: "test",
      title: "Test it on history",
      detail: "See how the rules would have behaved on past prices before anything trades. Past results don't guarantee future ones.",
      done: setup.has_backtest,
      action: <Button asChild size="sm"><Link href="/strategies?tab=mine">Test a strategy</Link></Button>,
    },
    {
      key: "start",
      title: "Start in Demo",
      detail: "Activate the strategy on your Paper or demo account, then press Start. You can stop at any moment with one click.",
      done: setup.has_active_strategy && setup.trading_started,
      action: setup.has_active_strategy ? startAction : <Button asChild size="sm"><Link href="/strategies?tab=mine">Activate a strategy</Link></Button>,
    },
  ];
}

export function isSetupComplete(setup: Setup | undefined): boolean {
  return Boolean(setup && setup.has_account && setup.has_strategy && setup.has_active_strategy && setup.trading_started);
}

/** Friendly first-run guide shown on Home until the basics are in place: a four-stop route. */
export function SetupChecklist({ setup, startAction }: { setup: Setup; startAction: ReactNode }) {
  const steps = checklistSteps(setup, startAction);
  const done = steps.filter((s) => s.done).length;
  const current = steps.findIndex((s) => !s.done);
  return (
    <Card className="surface-hero">
      <CardHeader>
        <p className="eyebrow text-brand-ink">Your flight plan</p>
        <CardTitle className="text-xl font-extrabold sm:text-2xl">Get started in four steps</CardTitle>
        <CardDescription>Everything starts in Demo — no real money is involved until you deliberately choose otherwise.</CardDescription>
        <div className="mt-3 flex items-center gap-3">
          <Progress value={(done / steps.length) * 100} className="h-1.5 flex-1" aria-label={`${done} of ${steps.length} steps done`} />
          <span className="num text-xs font-bold text-fg-muted">{done}/{steps.length}</span>
        </div>
      </CardHeader>
      <CardContent>
        <ol className="grid items-start gap-3 md:grid-cols-4">
          {steps.map((step, i) => {
            const isCurrent = i === current;
            return (
              <li key={step.key} aria-current={isCurrent ? "step" : undefined}
                className={cn("relative flex gap-3 rounded-lg p-4 transition-colors md:flex-col",
                  isCurrent ? "bg-card shadow-raised ring-2 ring-primary" : "bg-surface-raised ring-1 ring-line")}>
                <span className={cn("num flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-extrabold",
                  step.done ? "bg-positive text-positive-foreground" : isCurrent ? "bg-primary text-primary-foreground" : "bg-surface-hover text-fg-muted")}>
                  {step.done ? <Check className="size-4" strokeWidth={3} aria-label="Done" /> : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className={cn("text-sm font-bold text-fg", step.done && "text-fg-muted line-through decoration-fg-subtle")}>{step.title}</p>
                  {!step.done && <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">{step.detail}</p>}
                  {isCurrent && <div className="mt-3">{step.action}</div>}
                </div>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
