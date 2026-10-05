"use client";

import { CircleCheck, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useSession } from "@/components/providers/SessionProvider";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Field, TextInput } from "@/components/ui/Fields";
import { KeyValue, Loading, Notice } from "@/components/ui/Misc";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { describeAuditAction, formatDateTime, formatRelative } from "@/lib/format";
import { useAction, useApi } from "@/lib/hooks";
import type { AuditEntry, Paginated, SystemStatus } from "@/lib/types";

export function SettingsScreen() {
  const { user, isOwner } = useSession();
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Your sign-in security, system health and the audit trail." />
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title="Profile" />
          <CardBody><KeyValue items={[["Name", user.name], ["Email", user.email], ["Role", user.role === "owner" ? "Owner — full control" : "Viewer — read only"], ["Last sign-in", formatRelative(user.last_login_at)]]} /></CardBody>
        </Card>
        <Security />
      </div>
      <SystemCard />
      {isOwner && <AuditCard />}
    </div>
  );
}

function Security() {
  const { user, refresh } = useSession();
  const [password, setPassword] = useState("");
  const [setup, setSetup] = useState<{ secret: string; qr_svg: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const action = useAction();

  const begin = async () => {
    const res = await action.run(() => api<{ secret: string; qr_svg: string }>("/auth/mfa/setup", { method: "POST", body: { password } }));
    if (res) { setSetup(res); setPassword(""); }
  };
  const confirm = async () => {
    const res = await action.run(() => api<{ recovery_codes: string[] }>("/auth/mfa/confirm", { method: "POST", body: { code } }));
    if (res) { setCodes(res.recovery_codes); setSetup(null); setCode(""); await refresh(); }
  };
  const disable = async () => {
    const res = await action.run(() => api("/auth/mfa/disable", { method: "POST", body: { password, code } }));
    if (res !== null) { setPassword(""); setCode(""); await refresh(); }
  };
  const regenerate = async () => {
    const res = await action.run(() => api<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes", { method: "POST", body: { password } }));
    if (res) { setCodes(res.recovery_codes); setPassword(""); }
  };

  return (
    <Card>
      <CardHeader title={<span id="security" className="flex items-center gap-2"><ShieldCheck className="size-4 text-accent" aria-hidden /> Two-factor authentication</span>}
        action={user.mfa_enabled ? <Badge tone="positive" dot>On</Badge> : <Badge tone="warning" dot>Off</Badge>} />
      <CardBody className="space-y-4">
        {codes && (
          <Notice tone="success" title="Save these recovery codes now">
            <p>Each works once if you lose your phone. They will not be shown again.</p>
            <ul className="num mt-2 grid grid-cols-2 gap-1 text-fg">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
          </Notice>
        )}
        {!user.mfa_enabled && !setup && (
          <>
            <p className="text-sm text-fg-muted">Protect your account with a 6-digit code from an authenticator app (Google Authenticator, 1Password, Authy…). Required before LIVE trading can be enabled.</p>
            <Field label="Confirm your password"><TextInput type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></Field>
            <Button variant="primary" onClick={() => void begin()} disabled={!password || action.busy}>Set up two-factor authentication</Button>
          </>
        )}
        {setup && (
          <div className="space-y-4">
            <p className="text-sm text-fg-muted">1. Scan this code with your authenticator app (or enter the key manually).</p>
            <div className="flex flex-wrap items-center gap-5">
              <div className="rounded-lg bg-white p-2" dangerouslySetInnerHTML={{ __html: setup.qr_svg }} aria-label="QR code" />
              <code className="num break-all text-xs text-fg-muted">{setup.secret}</code>
            </div>
            <p className="text-sm text-fg-muted">2. Enter the 6-digit code it shows.</p>
            <Field label="Code"><TextInput value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6} className="num tracking-widest" autoComplete="one-time-code" /></Field>
            <Button variant="primary" onClick={() => void confirm()} disabled={code.length !== 6 || action.busy}>Turn on</Button>
          </div>
        )}
        {user.mfa_enabled && (
          <>
            <p className="flex items-center gap-2 text-sm text-fg-muted"><CircleCheck className="size-4 text-positive" aria-hidden /> Sign-in requires a code from your authenticator app.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Password"><TextInput type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></Field>
              <Field label="Current code (to turn off)"><TextInput value={code} onChange={(e) => setCode(e.target.value)} className="num" /></Field>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void regenerate()} disabled={!password || action.busy}>New recovery codes</Button>
              <Button variant="danger-outline" onClick={() => void disable()} disabled={!password || !code || action.busy}>Turn off</Button>
            </div>
          </>
        )}
        {action.error && <Notice tone="danger">{action.error}</Notice>}
      </CardBody>
    </Card>
  );
}

function SystemCard() {
  const status = useApi<SystemStatus>("/system/status", undefined, 15000);
  const s = status.data;
  return (
    <Card>
      <CardHeader title="System" description="Configuration and health of the backend, the trading engine and the database" />
      <CardBody>
        {!s ? <Loading /> : (
          <div className="grid gap-x-8 md:grid-cols-2">
            <KeyValue items={[
              ["Database (MySQL)", s.database === "ok" ? <Badge key="d" tone="positive">OK</Badge> : <Badge key="d" tone="negative">Error</Badge>],
              ["Trading engine", s.engine.status === "ok" ? <Badge key="e" tone="positive">Reachable{s.engine.version ? ` · v${s.engine.version}` : ""}</Badge> : <Badge key="e" tone="negative">Unreachable</Badge>],
              ["Engine heartbeat", s.trading.engine_state],
              ["Queue", s.queue_connection],
            ]} />
            <KeyValue items={[
              ["LIVE trading lock", s.live_trading_enabled ? <Badge key="l" tone="live">Unlocked</Badge> : <Badge key="l" tone="positive">Locked</Badge>],
              ["Broker credential encryption", s.broker_vault_configured ? "Configured" : <span key="v" className="text-negative">Not configured — run php artisan fx:keys</span>],
              ["Deriv App ID", s.deriv_app_id_configured ? "Configured" : <span key="a" className="text-warning">Missing (DERIV_APP_ID)</span>],
              ["MFA required for everyone", s.mfa_required ? "Yes" : "No"],
            ]} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function AuditCard() {
  const audit = useApi<Paginated<AuditEntry>>("/audit", { per_page: 100 });
  return (
    <Card>
      <CardHeader title="Audit log" description="Append-only: the database refuses changes or deletions." />
      <DataTable caption="Audit log" rows={audit.data?.data ?? null} loading={audit.loading} error={audit.error} rowKey={(r) => r.id} columns={[
        { key: "t", header: "Time", cell: (r) => <span className="text-xs text-fg-subtle">{formatDateTime(r.occurred_at)}</span> },
        { key: "a", header: "Action", cell: (r) => describeAuditAction(r.action) },
        { key: "u", header: "Who", hideBelow: "sm", cell: (r) => <span className="text-fg-muted">{r.actor_label}</span> },
        { key: "o", header: "Result", cell: (r) => <Badge tone={r.outcome === "success" ? "positive" : r.outcome === "denied" ? "warning" : "negative"}>{r.outcome}</Badge> },
        { key: "ip", header: "IP", hideBelow: "lg", cell: (r) => <span className="num text-xs text-fg-subtle">{r.ip_address ?? "—"}</span> },
      ]} />
    </Card>
  );
}
