import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-accent text-sm font-bold text-canvas">
            2k
          </span>
          <div>
            <p className="text-base font-semibold tracking-tight">
              2kFX <span className="text-fg-muted">ROBOT</span>
            </p>
            <p className="text-xs text-fg-subtle">Trading research &amp; automation</p>
          </div>
        </div>
        <Suspense>
          <LoginForm />
        </Suspense>
        <p className="mt-6 text-xs leading-relaxed text-fg-subtle">
          Accounts are created by the operator with <code className="num text-fg-muted">fxrobot create-user</code>.
          There is no public sign-up.
        </p>
      </div>
    </main>
  );
}
