"use client";

import { Clock, LogOut, MessageCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";
import type { User } from "@/lib/types";

/** The admin's WhatsApp number, digits only (international format). */
export const SUPPORT_WHATSAPP = (process.env.NEXT_PUBLIC_SUPPORT_WHATSAPP ?? "255769190100").replace(/\D/g, "");

export function whatsappLink(user: Pick<User, "name" | "email">): string {
  const text = `Hello, I just created a 2kPilot account (${user.name}, ${user.email}). Please approve it.`;
  return `https://wa.me/${SUPPORT_WHATSAPP}?text=${encodeURIComponent(text)}`;
}

/**
 * Shown instead of the whole dashboard until an admin approves the account.
 * Checks again by itself every 30 seconds, so the dashboard opens on its own.
 */
export function PendingApproval({ user, onCheck, onLogout }: { user: User; onCheck: () => Promise<void>; onLogout: () => Promise<void> }) {
  const [checking, setChecking] = useState(false);
  const check = async () => {
    setChecking(true);
    try {
      await onCheck();
    } finally {
      setChecking(false);
    }
  };
  useEffect(() => {
    const timer = window.setInterval(() => void onCheck(), 30_000);
    return () => window.clearInterval(timer);
  }, [onCheck]);

  return (
    <AuthShell footer={<>Signed in as <span className="font-bold text-white">{user.email}</span></>}>
      <div className="space-y-5" role="status">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/15 text-[#C8A2F0]" aria-hidden>
          <Clock className="size-6" />
        </span>
        <div className="space-y-2">
          <h1 className="text-2xl font-extrabold">Waiting for approval</h1>
          <p className="text-sm leading-relaxed text-white/70">
            Thanks for signing up, {user.name}. An administrator needs to approve your account before you can use 2kPilot.
            This page opens the dashboard by itself as soon as you are approved.
          </p>
        </div>
        <Button asChild size="lg" className="w-full bg-[#25D366] text-black hover:bg-[#1ebe5b]">
          <a href={whatsappLink(user)} target="_blank" rel="noopener noreferrer">
            <MessageCircle aria-hidden /> Ask for approval on WhatsApp
          </a>
        </Button>
        <div className="grid grid-cols-2 gap-3">
          <Button variant="outline" onClick={() => void check()} disabled={checking}>
            <RefreshCw aria-hidden className={checking ? "animate-spin" : undefined} /> Check again
          </Button>
          <Button variant="ghost" onClick={() => void onLogout()}>
            <LogOut aria-hidden /> Log out
          </Button>
        </div>
      </div>
    </AuthShell>
  );
}
