"use client";

import { Cable, FlaskConical, Plus } from "lucide-react";
import Link from "next/link";
import { CardsSkeleton, EmptyState, SectionHeader } from "@/components/app/states";
import { useAppData } from "@/components/providers/AppDataProvider";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AccountCard } from "./AccountCard";

/** Settings → Brokers: one card per connected broker account, exactly as the engine reports it. */
export function BrokersScreen() {
  const { accounts, reloadAccounts } = useAppData();

  return (
    <div>
      <SectionHeader
        title="Brokers"
        description="Each card shows what the broker reported. Nothing is shown as connected unless the trading engine actually connected it."
        actions={<Button asChild><Link href="/settings/brokers/new"><Plus aria-hidden /> Add broker</Link></Button>}
      />
      {accounts === null ? (
        <CardsSkeleton />
      ) : accounts.length === 0 ? (
        <Card>
          <EmptyState
            icon={Cable}
            title="No broker connected yet"
            action={
              <>
                <Button asChild><Link href="/settings/brokers/new"><FlaskConical aria-hidden /> Start with Paper</Link></Button>
                <Button asChild variant="outline"><Link href="/settings/brokers/new">Connect Deriv demo</Link></Button>
              </>
            }
          >
            Start with Paper (no money) or connect Deriv demo. Paper needs no sign-up; a Deriv demo account uses real prices with virtual money.
          </EmptyState>
        </Card>
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {accounts.map((a) => (
            <li key={a.id} className="min-w-0">
              <AccountCard account={a} onChange={() => void reloadAccounts()} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
