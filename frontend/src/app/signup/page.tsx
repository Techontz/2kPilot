import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/auth/AuthShell";
import { SignupForm } from "./SignupForm";

export const metadata: Metadata = { title: { absolute: "Create account · 2kPilot" } };

export default function SignupPage() {
  return (
    <AuthShell footer={<>Already have an account? <Link href="/login" className="font-bold text-white underline-offset-4 hover:text-[#C8A2F0] hover:underline">Sign in</Link></>}>
      <SignupForm />
    </AuthShell>
  );
}
