"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/inputClass";
import { ApiError, apiRequest } from "@/lib/api";
import { safeNextPath } from "@/lib/redirect";
import type { SessionInfo } from "@/lib/types";


export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(
    params.get("expired") ? "Your session expired. Please sign in again." : null,
  );
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiRequest<SessionInfo>("/auth/login", { method: "POST", body: { email, password } });
      router.replace(safeNextPath(params.get("next")));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
      setBusy(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="rounded-xl border border-line bg-surface p-6">
      <h1 className="text-base font-semibold">Sign in</h1>
      <label className="mt-5 block text-sm text-fg-muted">
        Email
        <input
          className={inputClass}
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <label className="mt-4 block text-sm text-fg-muted">
        Password
        <input
          className={inputClass}
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {error && (
        <p role="alert" className="mt-4 rounded-lg bg-negative-soft px-3 py-2 text-sm text-negative">
          {error}
        </p>
      )}
      <Button type="submit" variant="primary" className="mt-5 w-full" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
