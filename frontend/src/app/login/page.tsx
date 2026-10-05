import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2.5">
          <span className="flex size-8 items-center justify-center rounded-md bg-accent text-xs font-bold text-canvas">2k</span>
          <span className="text-base font-semibold tracking-tight">2kFX ROBOT</span>
        </div>
        <Suspense>
          <LoginForm />
        </Suspense>
        <p className="mt-8 text-xs leading-relaxed text-fg-subtle">
          Trading involves risk of loss. 2kFX makes no claim that any strategy is profitable. New accounts are created by the operator
          (<code className="num">php artisan fx:user</code>).
        </p>
      </div>
    </main>
  );
}
