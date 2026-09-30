"use client";

import { useSession } from "@/components/providers/SessionProvider";
import { useSystemStatus } from "@/components/providers/SystemStatusProvider";
import { useApiResource } from "@/lib/useApiResource";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { formatDateTime } from "@/lib/format";
import { AuditLogTable } from "./AuditLogTable";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="text-right text-fg">{value}</dd>
    </div>
  );
}

export function SettingsScreen() {
  const { user, isOwner } = useSession();
  const { status } = useSystemStatus();
  const settings = useApiResource<Record<string, string | number | boolean>>("/settings", { refetchOnFocus: false });
  const s = settings.data;

  return (
    <>
      <PageHeader title="Settings" />
      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader title="Your account" />
            <CardBody>
              <dl className="divide-y divide-line">
                <Field label="Name" value={user.display_name} />
                <Field label="Email" value={user.email} />
                <Field label="Role" value={user.role} />
                <Field label="Last sign-in" value={formatDateTime(user.last_login_at)} />
              </dl>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="System" description="Server settings are changed in backend/.env, not from the dashboard." />
            <CardBody>
              <dl className="divide-y divide-line">
                <Field label="Version" value={<span className="num">{status?.version ?? "—"}</span>} />
                <Field label="Environment" value={status?.environment ?? "—"} />
                <Field label="Live trading hard lock" value={status?.trading.live_trading_locked ? "Locked" : "Unlocked"} />
                <Field label="Trading engine" value={s ? (s.engine_enabled ? `Enabled · tick ${s.engine_tick_seconds}s` : "Disabled (ENGINE_ENABLED=false)") : "—"} />
                <Field label="Database" value={<span className="num text-xs">{s ? String(s.database) : "—"}</span>} />
                <Field label="Credential encryption key" value={s ? (s.encryption_key_configured ? "Configured" : "Missing — MT5 accounts cannot be saved") : "—"} />
                <Field label="Secure cookies (HTTPS)" value={s ? (s.cookie_secure ? "On" : "Off (development)") : "—"} />
                <Field label="Session length / idle timeout" value={s ? `${s.session_ttl_minutes} / ${s.session_idle_timeout_minutes} min` : "—"} />
              </dl>
            </CardBody>
          </Card>
        </div>
        {isOwner && (
          <div id="audit">
            <AuditLogTable />
          </div>
        )}
      </div>
    </>
  );
}
