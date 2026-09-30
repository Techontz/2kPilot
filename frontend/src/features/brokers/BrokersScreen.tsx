"use client";

import { Cable, ClipboardCheck, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { useLiveRefresh } from "@/components/providers/StreamProvider";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";
import { Select, Toggle } from "@/components/ui/Fields";
import { ConnectionBadge, EmptyState, EnvBadge, Loading, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { Term } from "@/components/ui/Term";
import { apiRequest } from "@/lib/api";
import { formatMoney, formatTime } from "@/lib/format";
import type { BrokerConnection, Readiness, RiskProfile, TradingAccount } from "@/lib/types";
import { useAction } from "@/lib/useAction";
import { useApiResource } from "@/lib/useApiResource";
import { AddBrokerWizard } from "./AddBrokerWizard";

function ReadinessDialog({ accountId, onClose }: { accountId: string | null; onClose: () => void }) {
  const { data, error } = useApiResource<Readiness>(`/accounts/${accountId}/readiness`, { enabled: accountId !== null, refetchOnFocus: false });
  return (
    <Dialog open={accountId !== null} onClose={onClose} title="LIVE readiness checklist" size="lg">
      {!data && !error && <Loading />}
      {error && <Notice tone="danger">{error.message}</Notice>}
      {data && (
        <div className="space-y-4">
          <Notice tone={data.ready ? "success" : "info"} title={`${data.passed} of ${data.total} checks passed`}>
            {data.note}
          </Notice>
          <ul className="divide-y divide-line">
            {data.items.map((i) => (
              <li key={i.id} className="flex items-start justify-between gap-4 py-2.5 text-sm">
                <div>
                  <p className="text-fg">{i.label}</p>
                  <p className="text-xs text-fg-subtle">{i.detail}</p>
                </div>
                <span className={i.passed ? "text-xs font-medium text-positive" : "text-xs font-medium text-fg-subtle"}>
                  {i.passed ? "Pass" : "Not yet"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Dialog>
  );
}

function AccountRow({ account, profiles, onChanged }: { account: TradingAccount; profiles: RiskProfile[]; onChanged: () => void }) {
  const { isOwner } = useSession();
  const action = useAction();
  const patch = async (body: Record<string, unknown>) => {
    if (await action.run(() => apiRequest(`/accounts/${account.id}`, { method: "PATCH", body }))) onChanged();
  };
  return (
    <div className="rounded-lg border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-fg">{account.label}</p>
            <EnvBadge env={account.environment} />
          </div>
          <p className="mt-0.5 text-xs text-fg-subtle">
            {account.broker_account_id} · {account.server} · {account.currency}
            {account.leverage ? ` · 1:${account.leverage}` : ""}
          </p>
        </div>
        <dl className="grid grid-cols-3 gap-x-6 text-right text-xs">
          <div>
            <dt className="text-fg-subtle"><Term id="balance" /></dt>
            <dd className="num mt-0.5 text-sm text-fg">{formatMoney(account.balance)}</dd>
          </div>
          <div>
            <dt className="text-fg-subtle"><Term id="equity" /></dt>
            <dd className="num mt-0.5 text-sm text-fg">{formatMoney(account.equity)}</dd>
          </div>
          <div>
            <dt className="text-fg-subtle"><Term id="freeMargin" /></dt>
            <dd className="num mt-0.5 text-sm text-fg">{formatMoney(account.free_margin)}</dd>
          </div>
        </dl>
      </div>
      <div className="mt-4 grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
        <Toggle
          checked={account.trading_enabled}
          disabled={!isOwner || action.busy}
          onChange={(v) => void patch({ trading_enabled: v })}
          label="Trading enabled"
          description={account.trading_enabled ? "Enabled strategies may trade on this account." : "Monitoring only — no orders will be placed."}
        />
        <label className="text-sm">
          <span className="mb-1.5 block text-xs font-medium text-fg-muted">Risk profile</span>
          <Select
            value={account.risk_profile_id ?? ""}
            disabled={!isOwner || action.busy}
            onChange={(e) => void patch(e.target.value ? { risk_profile_id: e.target.value } : { clear_risk_profile: true })}
          >
            <option value="">None (cannot trade)</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </label>
      </div>
      {action.error && <Notice tone="danger" className="mt-3">{action.error}</Notice>}
      <p className="mt-3 text-xs text-fg-subtle">
        {account.open_positions ?? 0} open position(s) · {account.active_strategies ?? 0} active strateg{account.active_strategies === 1 ? "y" : "ies"} · synced {formatTime(account.synced_at)}
      </p>
    </div>
  );
}

export function BrokersScreen() {
  const { isOwner } = useSession();
  const connections = useApiResource<BrokerConnection[]>("/brokers/connections");
  const accounts = useApiResource<TradingAccount[]>("/accounts");
  const profiles = useApiResource<RiskProfile[]>("/risk/profiles", { refetchOnFocus: false });
  const [wizard, setWizard] = useState(false);
  const [removing, setRemoving] = useState<BrokerConnection | null>(null);
  const [readiness, setReadiness] = useState<string | null>(null);
  const [saved, setSaved] = useState<TradingAccount | null>(null);
  const action = useAction();
  const reload = () => {
    void connections.reload();
    void accounts.reload();
  };
  useLiveRefresh(["broker", "account"], reload, 1500);

  const accountsFor = (id: string) => (accounts.data ?? []).filter((a) => a.connection_id === id);

  return (
    <>
      <PageHeader
        title="Brokers"
        description="Trading accounts the robot can reach. Every account is verified with the broker before it is saved, and starts with trading disabled."
        actions={isOwner && <Button variant="primary" onClick={() => setWizard(true)}><Plus aria-hidden className="size-4" />Add broker</Button>}
      />
      {saved && (
        <Notice tone="success" title={`${saved.label} added`} className="mb-6">
          Trading is disabled. Next: assign a strategy on the Strategies page, then enable trading here when you are ready.
        </Notice>
      )}
      {connections.error && <Notice tone="danger">{connections.error.message}</Notice>}
      {!connections.data && !connections.error && <Loading />}
      {connections.data?.length === 0 && (
        <Card>
          <EmptyState
            icon={Cable}
            title="No broker connected yet"
            action={isOwner && <Button variant="primary" onClick={() => setWizard(true)}><Plus aria-hidden className="size-4" />Add broker</Button>}
          >
            Start with a <strong className="text-fg">Paper</strong> account to watch the whole pipeline work with simulated money, or connect a
            MetaTrader 5 demo account through the Windows bridge.
          </EmptyState>
        </Card>
      )}
      <div className="space-y-6">
        {connections.data?.map((c) => (
          <Card key={c.id}>
            <CardHeader
              title={
                <span className="flex flex-wrap items-center gap-2">
                  {c.label}
                  <span className="text-xs font-normal text-fg-subtle">{c.connector_type === "paper" ? "Paper / Simulation" : "MetaTrader 5 bridge"}</span>
                </span>
              }
              description={c.status_detail ?? undefined}
              action={
                <div className="flex items-center gap-2">
                  <ConnectionBadge status={c.status} />
                  {isOwner && (
                    <>
                      <Button size="sm" variant="ghost" aria-label="Reconnect" onClick={() => void action.run(() => apiRequest(`/brokers/connections/${c.id}/reconnect`, { method: "POST" })).then(reload)}>
                        <RefreshCw aria-hidden className="size-4" />
                      </Button>
                      <Button size="sm" variant="ghost" aria-label="Remove" onClick={() => setRemoving(c)}>
                        <Trash2 aria-hidden className="size-4" />
                      </Button>
                    </>
                  )}
                </div>
              }
            />
            <CardBody className="space-y-4">
              {c.connector_type === "mt5_bridge" && c.status !== "CONNECTED" && (
                <Notice tone="warning" title="MetaTrader 5 is not connected">
                  2kFX cannot reach the MT5 bridge or the terminal is not logged in. Check that the bridge is running on the Windows machine.
                </Notice>
              )}
              {accountsFor(c.id).map((a) => (
                <div key={a.id}>
                  <AccountRow account={a} profiles={profiles.data ?? []} onChanged={reload} />
                  <Button size="sm" variant="ghost" className="mt-2" onClick={() => setReadiness(a.id)}>
                    <ClipboardCheck aria-hidden className="size-4" /> LIVE readiness checklist
                  </Button>
                </div>
              ))}
            </CardBody>
          </Card>
        ))}
      </div>
      {action.error && <Notice tone="danger" className="mt-4">{action.error}</Notice>}
      <AddBrokerWizard open={wizard} onClose={() => setWizard(false)} onSaved={(a) => { setWizard(false); setSaved(a); reload(); }} />
      <ReadinessDialog accountId={readiness} onClose={() => setReadiness(null)} />
      <ConfirmDialog
        open={removing !== null}
        title={`Remove ${removing?.label ?? ""}?`}
        confirmLabel="Remove"
        confirmVariant="danger"
        busy={action.busy}
        error={action.error}
        onCancel={() => setRemoving(null)}
        onConfirm={() =>
          void action.run(() => apiRequest(`/brokers/connections/${removing?.id}`, { method: "DELETE" })).then((ok) => {
            if (ok !== null) {
              setRemoving(null);
              reload();
            }
          })
        }
      >
        <p>The stored (encrypted) credentials are deleted and the account stops trading.</p>
        <p>If the account has any trading history, it is <strong className="text-fg">archived</strong> instead of deleted, so the journal and analytics keep every record. Accounts with open positions cannot be removed.</p>
      </ConfirmDialog>
    </>
  );
}
