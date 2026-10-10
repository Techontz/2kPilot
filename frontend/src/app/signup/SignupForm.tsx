"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { FormField as Field } from "@/components/app/form-field";
import { Input as TextInput } from "@/components/ui/input";
import { Notice } from "@/components/app/states";
import { PasswordField } from "@/components/auth/PasswordField";
import { cn } from "@/lib/utils";
import { api, ensureCsrf } from "@/lib/api";
import { useAction } from "@/lib/hooks";

/** Public sign-up. The server signs the new user in, so success goes straight to the dashboard. */
export function SignupForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [acceptTerms, setAcceptTerms] = useState(false);
  const action = useAction();
  const fieldError = (field: string) => action.fieldErrors[field]?.[0] ?? null;
  const hasFieldErrors = Object.keys(action.fieldErrors).length > 0;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await ensureCsrf(true);
    const result = await action.run(() =>
      api("/auth/register", { method: "POST", body: { name, email, password, password_confirmation: confirmation, accept_terms: true } }),
    );
    if (result === null) return;
    setPassword("");
    setConfirmation("");
    router.replace("/");
  };

  return (
    <form onSubmit={submit} className="space-y-3.5 short:space-y-3 tiny:space-y-2.5">
      <div className="mb-5 short:mb-4 tiny:mb-3">
        <h1 className="text-[clamp(1.5rem,3.8vh,2.125rem)] leading-tight font-extrabold tracking-[-0.035em]">Create your account</h1>
        <p className="mt-1.5 text-[13px] leading-snug text-white/65 sm:text-sm">Start with a Paper account — everything is simulated until you connect a broker.</p>
      </div>
      {action.error && !hasFieldErrors && <Notice tone="danger">{action.error}</Notice>}
      <Field label="Name" error={fieldError("name")}>
        <TextInput value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required autoFocus maxLength={120} className="h-11 short:h-10 tiny:h-9" />
      </Field>
      <Field label="Email" error={fieldError("email")}>
        <TextInput type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required className="h-11 short:h-10 tiny:h-9" placeholder="you@example.com" />
      </Field>
      <PasswordField label="Password" hint="At least 10 characters, with upper- and lower-case letters and a number." error={fieldError("password")}
        value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required minLength={10} className="[&_input]:h-11 short:[&_input]:h-10 tiny:[&_input]:h-9" />
      <PasswordField label="Confirm password" error={fieldError("password_confirmation")}
        value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="new-password" required className="[&_input]:h-11 short:[&_input]:h-10 tiny:[&_input]:h-9" />
      <label className={cn("flex cursor-pointer items-start gap-3 rounded-xl px-3.5 py-3 text-[13px] ring-1 transition-colors",
        acceptTerms ? "bg-[rgb(158_79_224/0.12)] ring-[#9E4FE0]/60" : "bg-white/[0.04] ring-white/15 hover:ring-white/30")}>
        <input type="checkbox" checked={acceptTerms} onChange={(e) => setAcceptTerms(e.target.checked)} required className="mt-0.5 size-[18px] shrink-0 cursor-pointer accent-primary" />
        <span className="leading-snug">
          <span className="flex items-center gap-1.5 font-bold text-white"><AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden /> Risk acknowledgement</span>
          <span className="mt-0.5 block text-white/85">I understand trading involves risk and I may lose my entire balance</span>
        </span>
      </label>
      {fieldError("accept_terms") && <p role="alert" className="text-xs text-negative">{fieldError("accept_terms")}</p>}
      <Button type="submit" size="lg" className="h-11 w-full rounded-full text-[15px] font-bold" disabled={action.busy || !acceptTerms}>
        {action.busy && <Loader2 className="animate-spin" aria-hidden />}
        {action.busy ? "Creating account…" : "Create account"}
      </Button>
    </form>
  );
}
