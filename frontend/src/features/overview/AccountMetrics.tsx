import { StatCard } from "@/components/ui/StatCard";
import { Term } from "@/components/ui/Term";

/**
 * Account figures come only from a connected broker. Until one exists we
 * show an explicit dash — never a placeholder number.
 */
export function AccountMetrics({ connected }: { connected: boolean }) {
  const hint = connected ? undefined : "No account connected";
  const empty = <span className="text-fg-subtle">—</span>;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard label={<Term id="balance" />} value={empty} hint={hint} />
      <StatCard label={<Term id="equity" />} value={empty} hint={hint} />
      <StatCard label={<Term id="pnl">Today&apos;s P/L</Term>} value={empty} hint={hint} />
      <StatCard label={<Term id="openRisk" />} value={empty} hint={hint} />
    </div>
  );
}
