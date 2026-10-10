import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AuthShell } from "@/components/auth/AuthShell";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: { absolute: "Sign in · 2kPilot" } };

export default function LoginPage() {
  return (
    <AuthShell footer={<>No account? <Link href="/signup" className="font-bold text-white underline-offset-4 hover:text-[#C8A2F0] hover:underline">Create one</Link></>}>
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
