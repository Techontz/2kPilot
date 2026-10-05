"use client";

import { Cable, Plus } from "lucide-react";
import Link from "next/link";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, Loading } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { useApi } from "@/lib/hooks";
import type { RiskProfile } from "@/lib/types";
import { AccountCard } from "./AccountCard";

export function BrokersScreen() {
  const { accounts, reloadAccounts } = useAppData();
  const { isOwner } = useSession();
  const profiles = useApi<RiskProfile[]>("/risk/profiles");

  return (
    <div>
      <PageHeader
        title="Brokers"
        description="2kFX → Broker Manager → Broker Adapter → Broker → your account. Each card shows exactly what the broker reported — nothing is shown as connected unless the engine connected it."
        actions={isOwner && <Link href="/brokers/new"><Button variant="primary"><Plus className="size-4" aria-hidden /> Add broker</Button></Link>}
      />
      {!accounts ? <Loading /> : accounts.length === 0 ? (
        <Card>
          <EmptyState icon={Cable} title="No broker connected yet" action={isOwner && <Link href="/brokers/new"><Button variant="primary">Add broker</Button></Link>}>
            Start with <strong className="text-fg">Paper Trading</strong> to learn without real money, then add a Deriv or MetaTrader 5 demo account.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {accounts.map((a) => <AccountCard key={a.id} account={a} profiles={profiles.data ?? []} onChange={() => void reloadAccounts()} />)}
        </div>
      )}
    </div>
  );
}
