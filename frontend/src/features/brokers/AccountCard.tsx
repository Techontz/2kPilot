"use client";

import { MoreHorizontal, PlugZap, RefreshCw, Trash2, Unplug } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Select, Toggle } from "@/components/ui/Fields";
import { ConnectionBadge, EnvBadge } from "@/components/ui/Misc";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatMoney, formatRelative } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { Account, RiskProfile } from "@/lib/types";

const ACCENT = { PAPER: "border-t-fg-subtle", DEMO: "border-t-info", LIVE: "border-t-live", UNKNOWN: "border-t-warning" };

/** The account card: everything you need to know about one broker account. */
export function AccountCard({ account, profiles, onChange }: { account: Account; profiles: RiskProfile[]; onChange: () => void }) {
  const { isOwner } = useSession();
  const action = useAction();
  const [menu, setMenu] = useState(false);
  const [confirm, setConfirm] = useState<"disconnect" | "remove" | null>(null);

  const patch = (body: Record<string, unknown>) =>
    action.run(() => api(`/accounts/${account.id}`, { method: "PATCH", body })).then((r) => r !== null && onChange());
  const post = (path: string) => action.run(() => api(path, { method: "POST" })).then((r) => r !== null && onChange());
  const remove = () =>
    action.run(() => api(`/brokers/${account.connection_id}`, { method: "DELETE" })).then((r) => {
      if (r !== null) { setConfirm(null); onChange(); }
    });
  const connected = account.connection_status === "CONNECTED";

  return (
    <article className={cn("flex min-w-0 flex-col rounded-xl border border-t-2 border-line bg-surface", ACCENT[account.environment])} aria-label={`${account.label} account`}>
      <header className="flex items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <p className="text-xs font-medium text-fg-subtle">{account.broker}</p>
          <h3 className="truncate text-base font-semibold text-fg">{account.label}</h3>
          <p className="num truncate text-xs text-fg-subtle">{account.broker_account_id}{account.server ? ` · ${account.server}` : ""}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <EnvBadge env={account.environment} />
          {isOwner && (
            <div className="relative">
              <button type="button" onClick={() => setMenu((v) => !v)} className="rounded-md p-1 text-fg-muted hover:bg-surface-raised" aria-label="Account actions" aria-expanded={menu}>
                <MoreHorizontal className="size-4" />
              </button>
              {menu && (
                <div className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-line-strong bg-surface-raised p-1 shadow-xl shadow-black/40" onMouseLeave={() => setMenu(false)}>
                  <MenuItem icon={RefreshCw} onClick={() => { setMenu(false); void post(`/accounts/${account.id}/sync`); }}>Sync now</MenuItem>
                  {account.connection_enabled
                    ? <MenuItem icon={Unplug} onClick={() => { setMenu(false); setConfirm("disconnect"); }}>Disconnect</MenuItem>
                    : <MenuItem icon={PlugZap} onClick={() => { setMenu(false); void post(`/brokers/${account.connection_id}/reconnect`); }}>Reconnect</MenuItem>}
                  <MenuItem icon={Trash2} danger onClick={() => { setMenu(false); setConfirm("remove"); }}>Remove</MenuItem>
                </div>
              )}
            </div>
          )}
        </div>
      </header>
      <div className="px-5 pt-3">
        <ConnectionBadge status={account.connection_status} />
        {!connected && account.connection_detail && <p className="mt-1 text-xs text-fg-subtle">{account.connection_detail}</p>}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-5 py-4 text-sm">
        <Item label="Balance" value={formatMoney(account.balance)} />
        <Item label="Equity" value={formatMoney(account.equity)} />
        <Item label="Currency" value={account.currency} />
        <Item label="Last sync" value={formatRelative(account.synced_at)} />
        <div className="col-span-2">
          <dt className="text-xs text-fg-subtle">Active strategy</dt>
          <dd className="mt-0.5 truncate text-fg">{account.active_strategies.length ? account.active_strategies.join(", ") : <span className="text-fg-muted">None</span>}</dd>
        </div>
      </dl>
      <div className="mt-auto space-y-3 border-t border-line px-5 py-4">
        <label className="block text-xs text-fg-subtle">
          Risk profile
          <Select className="mt-1" value={account.risk_profile?.id ?? ""} disabled={!isOwner || action.busy}
            onChange={(e) => void patch({ risk_profile_id: e.target.value || null })}>
            <option value="">— none (cannot trade) —</option>
            {profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </label>
        <Toggle
          checked={account.trading_enabled}
          disabled={!isOwner || action.busy}
          onChange={(next) => void patch({ trading_enabled: next })}
          label="Trading enabled"
          description={account.trading_enabled ? "Strategies and manual tickets may trade (risk engine still decides)." : "Off: nothing can trade on this account."}
        />
        {account.capabilities?.pending_orders === false && <Badge tone="neutral">Market orders only</Badge>}
        {action.error && <p role="alert" className="text-xs text-negative">{action.error}</p>}
      </div>
      <ConfirmDialog open={confirm === "disconnect"} title={`Disconnect ${account.label}?`} confirmLabel="Disconnect" confirmVariant="danger" busy={action.busy} error={action.error}
        onCancel={() => setConfirm(null)} onConfirm={() => void post(`/brokers/${account.connection_id}/disconnect`).then(() => setConfirm(null))}>
        <p>The engine stops monitoring this account and trading on it is switched off. Open positions stay open at the broker.</p>
      </ConfirmDialog>
      <ConfirmDialog open={confirm === "remove"} title={`Remove ${account.label}?`} confirmLabel="Remove" confirmVariant="danger" busy={action.busy} error={action.error}
        onCancel={() => setConfirm(null)} onConfirm={() => void remove()}>
        <p>Its stored credentials are deleted. If the account has trading history it is archived instead, so your journal and analytics stay complete.</p>
      </ConfirmDialog>
    </article>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-subtle">{label}</dt>
      <dd className="num mt-0.5 truncate text-fg">{value}</dd>
    </div>
  );
}

function MenuItem({ icon: Icon, onClick, children, danger }: { icon: typeof RefreshCw; onClick: () => void; children: React.ReactNode; danger?: boolean }) {
  return (
    <button type="button" onClick={onClick} className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-hover", danger ? "text-negative" : "text-fg-muted hover:text-fg")}>
      <Icon className="size-4" aria-hidden /> {children}
    </button>
  );
}
