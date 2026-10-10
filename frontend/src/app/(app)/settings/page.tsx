import type { Metadata } from "next";
import { Suspense } from "react";
import { SettingsSection } from "@/features/settings/SettingsSection";

export const metadata: Metadata = { title: "Settings" };

export default function Page() {
  return (
    <Suspense>
      <SettingsSection />
    </Suspense>
  );
}
