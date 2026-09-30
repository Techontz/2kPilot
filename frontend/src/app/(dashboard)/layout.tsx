import { AppShell } from "@/components/layout/AppShell";
import { SessionProvider } from "@/components/providers/SessionProvider";
import { SystemStatusProvider } from "@/components/providers/SystemStatusProvider";

export default function DashboardLayout({ children }: LayoutProps<"/">) {
  return (
    <SessionProvider>
      <SystemStatusProvider>
        <AppShell>{children}</AppShell>
      </SystemStatusProvider>
    </SessionProvider>
  );
}
