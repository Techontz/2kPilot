"use client";

import { ArrowLeft, Loader2, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { FormField as Field } from "@/components/app/form-field";
import { PasswordField } from "@/components/auth/PasswordField";
import { Input as TextInput } from "@/components/ui/input";
import { api, ensureCsrf } from "@/lib/api";
import { useAction } from "@/lib/hooks";

/**
 * Only same-site, absolute paths are accepted as a post-login destination.
 * Browsers treat "\" like "/" (so "/\evil.com" is protocol-relative), hence the
 * explicit character check plus a resolved-origin check.
 */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || /[\\\u0000-\u001f]/.test(next)) return "/";
  const base = "http://tradepilot.invalid";
  try {
    const url = new URL(next, base);
    return url.origin === base ? `${url.pathname}${url.search}${url.hash}` : "/";
  } catch {
    return "/";
  }
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
      <form onSubmit={submitCode} className="space-y-5 short:space-y-4">
        <div>
          <span className="flex size-11 items-center justify-center rounded-full bg-white/[0.06] text-[#C8A2F0] ring-1 ring-white/10">
            <ShieldCheck className="size-5" aria-hidden />
          </span>
          <h1 className="mt-4 text-[clamp(1.5rem,3.6vh,1.875rem)] leading-tight font-extrabold tracking-[-0.03em]">Two-step sign-in</h1>
          <p className="mt-1.5 text-sm text-white/65">Enter the 6-digit code from your authenticator app, or a recovery code.</p>
        </div>
        <Field label="Code" error={action.error}>
          <TextInput value={code} onChange={(e) => setCode(e.target.value)} autoFocus autoComplete="one-time-code" inputMode="text" required maxLength={20}
            placeholder="••••••" className="num h-14 text-center text-2xl! font-extrabold tracking-[0.45em] placeholder:tracking-[0.45em] placeholder:text-fg-subtle/50" />
        </Field>
        <Button type="submit" size="lg" className="h-11 w-full rounded-full text-[15px] font-bold" disabled={action.busy || code.length < 6}>
          {action.busy && <Loader2 className="animate-spin" aria-hidden />}
          {action.busy ? "Checking…" : "Verify and sign in"}
        </Button>
        <button type="button" className="mx-auto flex items-center gap-1.5 text-sm font-semibold text-white/65 hover:text-white" onClick={() => { setStep("password"); setCode(""); action.reset(); }}>
          <ArrowLeft className="size-4" aria-hidden /> Use a different account
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={submitPassword} className="space-y-4">
      <div className="mb-6 short:mb-5">
        <h1 className="text-[clamp(1.75rem,4.2vh,2.25rem)] leading-tight font-extrabold tracking-[-0.035em]">Sign in</h1>
        <p className="mt-1.5 text-sm text-white/65">Welcome back. Your robot keeps running while you are away.</p>
      </div>
      <Field label="Email">
        <TextInput type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required autoFocus className="h-11 short:h-10" placeholder="you@example.com" />
      </Field>
      <PasswordField label="Password" error={action.error} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required className="[&_input]:h-11 short:[&_input]:h-10" />
      <Button type="submit" size="lg" className="mt-2 h-11 w-full rounded-full text-[15px] font-bold" disabled={action.busy}>
        {action.busy && <Loader2 className="animate-spin" aria-hidden />}
        {action.busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
