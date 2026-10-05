"use client";

import { AlertOctagon, Lock, Plus, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { StopTradingButton } from "@/components/layout/TradingControls";
import { useAppData } from "@/components/providers/AppDataProvider";
import { useSession } from "@/components/providers/SessionProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Field, Segmented, TextInput } from "@/components/ui/Fields";
import { EnvBadge, Loading, Meter, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { Term } from "@/components/ui/Term";
import { api } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { deriveRobotStatus, MODE_INFO } from "@/lib/status";
import type { RiskProfile, RiskUsage, TradingMode } from "@/lib/types";
import { LIMIT_GROUPS, ProfileEditor } from "./ProfileEditor";

export function RiskScreen() {
  const { account, status, reloadStatus } = useAppData();
  const { isOwner } = useSession();
  const usage = useApi<RiskUsage>(account ? `/risk/usage/${account.id}` : null, undefined, 10000);
  const profiles = useApi<RiskProfile[]>("/risk/profiles");
  const [editing, setEditing] = useState<RiskProfile | null | "new">(null);

  return (
    <div className="space-y-6">
      <PageHeader title="Risk" description="Every automated and manual order passes these checks. A rule that cannot be evaluated fails safe." />
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title={<><Term id="killSwitch">STOP TRADING</Term> and operating mode</>} />
          <CardBody className="space-y-5">
            {status ? <GlobalControls onChange={() => void reloadStatus()} /> : <Loading />}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Emergency" />
          <CardBody>{isOwner ? <ClosePositions onDone={() => void reloadStatus()} /> : <p className="text-sm text-fg-muted">Only owners can use emergency actions.</p>}</CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={<span className="flex items-center gap-2">Limits in use{account && <> · {account.label} <EnvBadge env={account.environment} /></>}</span>} description={usage.data?.profile ? `Profile: ${usage.data.profile.name}` : "No risk profile assigned — this account cannot trade."} />
        <CardBody className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {!usage.data ? <Loading /> : usage.data.usage.map((u) => (
            <Meter key={u.key} label={u.label} used={u.used} limit={u.limit}
              detail={`${u.used === null ? "—" : u.used}${u.unit === "%" ? "%" : u.unit ? ` ${u.unit}` : ""} / ${u.limit === null ? "no limit" : `${u.limit}${u.unit === "%" ? "%" : ""}`}`} />
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Risk profiles" description="Assign a profile to each account on the Brokers page." action={isOwner && <Button size="sm" variant="primary" onClick={() => setEditing("new")}><Plus className="size-3.5" aria-hidden /> New profile</Button>} />
        <CardBody className="grid gap-4 lg:grid-cols-2">
          {profiles.data?.map((p) => (
            <div key={p.id} className="rounded-xl border border-line p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-fg">{p.name}</p>
                  <p className="text-xs text-fg-subtle">Used by {p.accounts_count ?? 0} account(s)</p>
                </div>
                {isOwner && <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>Edit</Button>}
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                {LIMIT_GROUPS.flatMap((g) => g.limits).slice(0, 10).map((l) => (
                  <div key={l.key} className="flex justify-between gap-2"><dt className="truncate text-fg-muted">{l.label}</dt><dd className="num text-fg">{p[l.key] === null ? <span className="text-fg-subtle">off</span> : String(Number(p[l.key]))}</dd></div>
                ))}
              </dl>
              <p className="mt-2 text-xs text-fg-subtle">Sessions: {p.allowed_sessions.length ? p.allowed_sessions.join(", ").toLowerCase() : "any"}{p.trading_hours_start ? ` · ${p.trading_hours_start}–${p.trading_hours_end} UTC` : ""}</p>
            </div>
          ))}
        </CardBody>
      </Card>
      {editing !== null && (
        <ProfileEditor key={editing === "new" ? "new" : editing.id} profile={editing === "new" ? null : editing} open onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); void profiles.reload(); void usage.reload(); }} />
      )}
    </div>
  );
}

function GlobalControls({ onChange }: { onChange: () => void }) {
  const { status } = useAppData();
  const { isOwner, user } = useSession();
  const [target, setTarget] = useState<TradingMode | null>(null);
  const [password, setPassword] = useState("");
  const [phrase, setPhrase] = useState("");
  const action = useAction();
  if (!status) return null;
  const robot = deriveRobotStatus(status);
  const change = async () => {
    if (!target) return;
    const ok = await action.run(() => api("/trading/mode", { method: "PUT", body: { mode: target, password: password || null, confirmation_phrase: phrase || null } }));
    if (ok !== null) { setTarget(null); setPassword(""); setPhrase(""); onChange(); }
  };
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm text-fg-muted">Robot</p>
          <p className="text-lg font-semibold text-fg">{robot.label}</p>
          <p className="text-sm text-fg-subtle">{robot.detail}</p>
        </div>
        <StopTradingButton />
      </div>
      <div className="grid gap-4 border-t border-line pt-5 sm:grid-cols-2">
        <div>
          <p className="mb-2 text-sm text-fg-muted">Operating mode</p>
          <Segmented label="Operating mode" value={status.trading_mode} onChange={(m) => { action.reset(); setTarget(m); }}
            options={(["BACKTEST", "DEMO", "LIVE"] as const).map((m) => ({ value: m, label: MODE_INFO[m].label }))} />
          <p className="mt-2 text-xs text-fg-subtle">{MODE_INFO[status.trading_mode].explanation} The mode can only change while trading is stopped.</p>
        </div>
        <div className="space-y-2">
          <p className="text-sm text-fg-muted">LIVE lock</p>
          {status.live_trading_locked
            ? <Badge tone="positive"><Lock className="size-3" aria-hidden /> Locked by the server</Badge>
            : <Badge tone="live">Unlocked by the operator</Badge>}
          <p className="text-xs text-fg-subtle">{status.live_trading_locked ? "LIVE_TRADING_ENABLED=false — no real-money account can trade, whatever is selected here." : "LIVE mode additionally needs two-factor authentication, your password and a typed confirmation."}</p>
        </div>
      </div>
      <ConfirmDialog open={target !== null && isOwner} title={`Switch to ${target ? MODE_INFO[target].label : ""} mode?`} confirmLabel="Switch mode"
        confirmVariant={target === "LIVE" ? "danger" : "primary"} busy={action.busy} error={action.error} onCancel={() => setTarget(null)} onConfirm={() => void change()}>
        <p>{target && MODE_INFO[target].explanation}</p>
        {target === "LIVE" && (
          <>
            {!user.mfa_enabled && <p className="text-warning">Turn on two-factor authentication first (Settings → Security).</p>}
            <Field label="Your password"><TextInput type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></Field>
            <Field label='Type "ENABLE LIVE TRADING"'><TextInput value={phrase} onChange={(e) => setPhrase(e.target.value)} /></Field>
          </>
        )}
      </ConfirmDialog>
    </>
  );
}

function ClosePositions({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [result, setResult] = useState<{ closed: number; failed: unknown[] } | null>(null);
  const action = useAction();
  const run = async () => {
    const res = await action.run(() => api<{ closed: number; failed: unknown[] }>("/trading/close-positions", { method: "POST", body: { confirm: true, reason: "Close positions from the Risk page" } }));
    if (res) { setResult(res); setOpen(false); setTyped(""); onDone(); }
  };
  return (
    <div className="space-y-3">
      <p className="flex items-start gap-2 text-sm text-fg-muted"><AlertOctagon className="mt-0.5 size-4 shrink-0 text-negative" aria-hidden />
        <span><strong className="text-fg">Close positions</strong> stops trading and closes <em>every</em> open position on every account at market. STOP TRADING alone never closes positions.</span></p>
      <Button variant="danger-outline" onClick={() => { action.reset(); setOpen(true); }}>Close all positions…</Button>
      {result && <Notice tone={result.failed.length ? "warning" : "success"}>Closed {result.closed} position(s){result.failed.length ? `; ${result.failed.length} could not be closed — see Notifications` : ""}.</Notice>}
      <ConfirmDialog open={open} title="Close every open position?" confirmLabel="Close all positions" confirmVariant="danger" busy={action.busy} error={action.error}
        confirmDisabled={typed !== "CLOSE"} onCancel={() => setOpen(false)} onConfirm={() => void run()}>
        <p>Trading is stopped first. Then every open position is closed at the current market price. This cannot be undone.</p>
        <Field label='Type "CLOSE" to confirm'><TextInput value={typed} onChange={(e) => setTyped(e.target.value)} /></Field>
      </ConfirmDialog>
      <p className="flex items-center gap-1.5 text-xs text-fg-subtle"><ShieldCheck className="size-3.5" aria-hidden /> Audited, with your name and the time.</p>
    </div>
  );
}
