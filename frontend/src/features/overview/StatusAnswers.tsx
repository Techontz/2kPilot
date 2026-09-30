import { Bot, Cable, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { ModeBadge } from "@/components/layout/ModeBadge";
import { Badge } from "@/components/ui/Badge";
import { Term } from "@/components/ui/Term";
import { cn } from "@/lib/cn";
import { deriveRobotStatus, MODE_INFO } from "@/lib/status";
import type { SystemStatus } from "@/lib/types";

interface AnswerProps {
  icon: typeof Bot;
  question: string;
  answer: ReactNode;
  detail: ReactNode;
  href: string;
  highlight?: boolean;
}

function Answer({ icon: Icon, question, answer, detail, href, highlight }: AnswerProps) {
  return (
    <Link
      href={href}
      className={cn(
        "group rounded-xl border bg-surface p-5 transition-colors hover:bg-surface-raised",
        highlight ? "border-live/60" : "border-line",
      )}
    >
      <div className="flex items-center gap-2 text-xs font-medium tracking-wide text-fg-subtle uppercase">
        <Icon aria-hidden className="size-3.5" />
        {question}
      </div>
      <div className="mt-3">{answer}</div>
      <p className="mt-2 text-sm leading-relaxed text-fg-muted">{detail}</p>
    </Link>
  );
}

/** The three questions a user must be able to answer within seconds. */
export function StatusAnswers({ status }: { status: SystemStatus }) {
  const robot = deriveRobotStatus(status.trading);
  const mode = status.trading.trading_mode;
  const accounts = status.broker_accounts_connected;
  const total = status.broker_accounts_total;

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Answer
        icon={Bot}
        question="Is the robot running?"
        href="/risk"
        answer={
          <Badge tone={robot.tone} dot className="px-2.5 py-1 text-sm">
            {robot.label}
          </Badge>
        }
        detail={robot.detail}
      />
      <Answer
        icon={ShieldCheck}
        question="Demo or live?"
        href="/trading"
        highlight={mode === "LIVE"}
        answer={
          <div className="flex items-center gap-2">
            <ModeBadge mode={mode} />
            {status.trading.live_trading_locked && <span className="text-xs text-fg-subtle">Live is locked on this server</span>}
          </div>
        }
        detail={MODE_INFO[mode].explanation}
      />
      <Answer
        icon={Cable}
        question="Which account?"
        href="/brokers"
        answer={
          <span className="text-sm font-semibold text-fg">
            {total === 0 ? "No account yet" : `${accounts} of ${total} account${total > 1 ? "s" : ""} connected`}
          </span>
        }
        detail={
          total === 0 ? (
            <>
              Add a Paper account to try the full pipeline, or a MetaTrader 5 <Term id="demoAccount">demo account</Term>.
            </>
          ) : accounts < total ? (
            "Some connections are down — see Brokers."
          ) : (
            "All connections are up. Manage them on the Brokers page."
          )
        }
      />
    </div>
  );
}
