"use client";

import { CircleCheck, Copy, KeyRound, ShieldCheck, UserRound } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/app/badges";
import { ConfirmDialog } from "@/components/app/confirm-dialog";
import { KeyValue, Notice } from "@/components/app/states";
import { useSession } from "@/components/providers/SessionProvider";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import { useAction } from "@/lib/hooks";

/** Settings → Security: profile, password and two-factor authentication. */
export function SecurityPanel() {
  return (
    <div className="grid items-start gap-6 xl:grid-cols-2">
      <div className="space-y-6">
        <ProfileCard />
        <ChangePasswordCard />
      </div>
      <MfaCard />
    </div>
  );
}

export function ProfileCard() {
  const { user } = useSession();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><UserRound className="size-4 text-fg-muted" aria-hidden /> Profile</CardTitle>
      </CardHeader>
      <CardContent>
        <KeyValue items={[
          ["Name", user.name],
          ["Email", <span key="e" className="break-all">{user.email}</span>],
          ["Role", user.role === "admin" ? "Administrator" : "User"],
          ["Last sign-in", <span key="l" title={formatDateTime(user.last_login_at)}>{formatRelative(user.last_login_at)}</span>],
        ]} />
      </CardContent>
    </Card>
  );
}

function Field({ label, error, children, id, hint }: { label: string; error?: string | null; children: ReactNode; id: string; hint?: string }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-fg-muted">{hint}</p>}
      {error && <p id={`${id}-err`} role="alert" className="text-sm text-negative">{error}</p>}
    </div>
  );
}

function ChangePasswordCard() {
  const ids = { current: useId(), next: useId(), confirm: useId() };
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const submit = async () => {
    setBusy(true);
    setErrors({});
    try {
      await api("/auth/password", { method: "PUT", body: { current_password: current, password: next, password_confirmation: confirm } });
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success("Password changed", { description: "Other browsers signed in to your account will be signed out." });
    } catch (e) {
      if (e instanceof ApiError) {
        const fields: Record<string, string> = {};
        for (const [k, v] of Object.entries(e.fieldErrors)) if (v[0]) fields[k] = v[0];
        if (e.code === "password_incorrect") fields.current_password = e.message;
        if (Object.keys(fields).length === 0) fields.form = e.message;
        setErrors(fields);
      } else {
        setErrors({ form: "Something went wrong. Try again." });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><KeyRound className="size-4 text-fg-muted" aria-hidden /> Change password</CardTitle>
        <CardDescription>Use a long password you don&apos;t use anywhere else.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <Field id={ids.current} label="Current password" error={errors.current_password}>
            <Input id={ids.current} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)}
              aria-invalid={Boolean(errors.current_password)} aria-describedby={errors.current_password ? `${ids.current}-err` : undefined} />
          </Field>
          <Field id={ids.next} label="New password" error={errors.password}>
            <Input id={ids.next} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)}
              aria-invalid={Boolean(errors.password)} aria-describedby={errors.password ? `${ids.next}-err` : undefined} />
          </Field>
          <Field id={ids.confirm} label="Repeat new password" error={errors.password_confirmation ?? (confirm && next !== confirm ? "The passwords don't match yet." : null)}>
            <Input id={ids.confirm} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
              aria-invalid={Boolean(errors.password_confirmation)} />
          </Field>
          {errors.form && <Notice tone="danger">{errors.form}</Notice>}
          <Button type="submit" disabled={busy || !current || !next || next !== confirm}>{busy ? "Saving…" : "Change password"}</Button>
        </form>
      </CardContent>
    </Card>
  );
}

function MfaCard() {
  const { user, refresh } = useSession();
  const ids = { password: useId(), code: useId(), offPassword: useId(), offCode: useId() };
  const [password, setPassword] = useState("");
  const [setup, setSetup] = useState<{ secret: string; qr_svg: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [confirmOff, setConfirmOff] = useState(false);
  const action = useAction();

  const begin = async () => {
    const res = await action.run(() => api<{ secret: string; qr_svg: string }>("/auth/mfa/setup", { method: "POST", body: { password } }));
    if (res) {
      setSetup(res);
      setPassword("");
    }
  };
  const turnOn = async () => {
    const res = await action.run(() => api<{ recovery_codes: string[] }>("/auth/mfa/confirm", { method: "POST", body: { code } }));
    if (res) {
      setCodes(res.recovery_codes);
      setSetup(null);
      setCode("");
      toast.success("Two-factor authentication is on");
      await refresh();
    }
  };
  const turnOff = async () => {
    const res = await action.run(() => api("/auth/mfa/disable", { method: "POST", body: { password, code } }));
    if (res !== null) {
      setPassword("");
      setCode("");
      setCodes(null);
      setConfirmOff(false);
      toast.success("Two-factor authentication is off");
      await refresh();
    }
  };
  const regenerate = async () => {
    const res = await action.run(() => api<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes", { method: "POST", body: { password } }));
    if (res) {
      setCodes(res.recovery_codes);
      setPassword("");
      toast.success("New recovery codes created", { description: "The old ones no longer work." });
    }
  };
  const copyCodes = async () => {
    if (!codes) return;
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      toast.success("Recovery codes copied");
    } catch {
      toast.error("Could not copy — select and copy them by hand.");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-brand-ink" aria-hidden /> Two-factor authentication</CardTitle>
        <CardDescription>A 6-digit code from an authenticator app (Google Authenticator, 1Password, Authy…) at every sign-in. Required for real-money trading.</CardDescription>
        <CardAction>{user.mfa_enabled ? <Pill tone="positive" dot>On</Pill> : <Pill tone="warning" dot>Off</Pill>}</CardAction>
      </CardHeader>
      <CardContent className="space-y-4" aria-live="polite">
        {codes && (
          <Notice tone="success" title="Save these recovery codes now"
            action={<Button size="sm" variant="outline" onClick={() => void copyCodes()}><Copy aria-hidden /> Copy</Button>}>
            <p>Each works once if you lose your phone. They will not be shown again.</p>
            <ul className="num mt-2 grid grid-cols-2 gap-1 text-fg select-all" aria-label="Recovery codes">
              {codes.map((c) => <li key={c}>{c}</li>)}
            </ul>
          </Notice>
        )}

        {!user.mfa_enabled && !setup && (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void begin(); }}>
            <Field id={ids.password} label="Confirm your password">
              <Input id={ids.password} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
            </Field>
            <Button type="submit" disabled={!password || action.busy}>Set up two-factor authentication</Button>
          </form>
        )}

        {setup && (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void turnOn(); }}>
            <p className="text-sm text-fg-muted">1. Scan this QR code with your authenticator app, or type the key by hand.</p>
            <div className="flex flex-wrap items-center gap-4">
              {/* The SVG is generated by our own backend (MfaController::setup). */}
              <div role="img" aria-label="QR code for your authenticator app" className="size-44 shrink-0 rounded-lg bg-white p-2 [&_svg]:size-full" dangerouslySetInnerHTML={{ __html: setup.qr_svg }} />
              <div className="min-w-0 space-y-1">
                <p className="text-xs text-fg-muted">Key</p>
                <code className="num block text-sm break-all text-fg select-all">{setup.secret}</code>
              </div>
            </div>
            <p className="text-sm text-fg-muted">2. Enter the 6-digit code the app shows.</p>
            <Field id={ids.code} label="Code">
              <Input id={ids.code} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric"
                maxLength={6} className="num max-w-40 tracking-widest" autoComplete="one-time-code" />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={code.length !== 6 || action.busy}>Turn on</Button>
              <Button type="button" variant="ghost" onClick={() => { setSetup(null); setCode(""); action.reset(); }}>Cancel</Button>
            </div>
          </form>
        )}

        {user.mfa_enabled && (
          <div className="space-y-4">
            <p className="flex items-center gap-2 text-sm text-fg-muted"><CircleCheck className="size-4 text-positive" aria-hidden /> Signing in needs a code from your authenticator app.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id={ids.offPassword} label="Password">
                <Input id={ids.offPassword} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
              </Field>
              <Field id={ids.offCode} label="Current code (to turn off)">
                <Input id={ids.offCode} value={code} onChange={(e) => setCode(e.target.value.trim())} inputMode="numeric" className="num" autoComplete="one-time-code" />
              </Field>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void regenerate()} disabled={!password || action.busy}>New recovery codes</Button>
              <Button variant="destructive" onClick={() => { action.reset(); setConfirmOff(true); }} disabled={!password || !code || action.busy}>Turn off…</Button>
            </div>
            <p className="text-xs text-fg-muted">New recovery codes need your password. Turning off needs your password and a current code.</p>
          </div>
        )}

        {action.error && !confirmOff && <Notice tone="danger">{action.error}</Notice>}
      </CardContent>
      <ConfirmDialog open={confirmOff} onOpenChange={setConfirmOff} title="Turn off two-factor authentication?" confirmLabel="Turn off" destructive
        busy={action.busy} error={action.error} onConfirm={() => void turnOff()}>
        <p>Anyone with your password could then sign in. Real-money trading needs two-factor authentication, so it can no longer be authorised.</p>
      </ConfirmDialog>
    </Card>
  );
}
