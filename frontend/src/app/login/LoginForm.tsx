"use client";

import { ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Fields";
import { api, ensureCsrf } from "@/lib/api";
import { useAction } from "@/lib/hooks";

/** Only same-site, absolute paths are accepted as a post-login destination. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const action = useAction();

  const done = () => router.replace(safeNext(params.get("next")));

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    await ensureCsrf(true);
    const result = await action.run(() => api<{ mfa_required?: boolean }>("/auth/login", { method: "POST", body: { email, password } }));
    if (result === null) return;
    setPassword("");
    if (result.mfa_required) setStep("mfa");
    else done();
  };

  const submitCode = async (e: React.FormEvent) => {
    e.preventDefault();
    const result = await action.run(() => api("/auth/mfa", { method: "POST", body: { code } }));
    if (result !== null) done();
  };

  if (step === "mfa") {
    return (
      <form onSubmit={submitCode} className="space-y-5">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold"><ShieldCheck className="size-5 text-accent" aria-hidden /> Two-step sign-in</h1>
          <p className="mt-1 text-sm text-fg-muted">Enter the 6-digit code from your authenticator app, or a recovery code.</p>
        </div>
        <Field label="Code" error={action.error}>
          <TextInput value={code} onChange={(e) => setCode(e.target.value)} autoFocus autoComplete="one-time-code" inputMode="text" required maxLength={20} className="num tracking-widest" />
        </Field>
        <Button type="submit" variant="primary" className="w-full" disabled={action.busy || code.length < 6}>
          {action.busy ? "Checking…" : "Verify and sign in"}
        </Button>
        <button type="button" className="text-sm text-fg-muted hover:text-fg" onClick={() => { setStep("password"); setCode(""); action.reset(); }}>
          ← Use a different account
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={submitPassword} className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-fg-muted">Welcome back. Your robot keeps running while you are away.</p>
      </div>
      <Field label="Email">
        <TextInput type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required autoFocus />
      </Field>
      <Field label="Password" error={action.error}>
        <TextInput type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
      </Field>
      <Button type="submit" variant="primary" className="w-full" disabled={action.busy}>
        {action.busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
