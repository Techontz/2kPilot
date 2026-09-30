import { AppShell } from "@/components/layout/AppShell";
import { SessionProvider } from "@/components/providers/SessionProvider";
import { StreamProvider } from "@/components/providers/StreamProvider";
import { SystemStatusProvider } from "@/components/providers/SystemStatusProvider";

export default function DashboardLayout({ children }: LayoutProps<"/">) {
  return (
    <SessionProvider>
      <StreamProvider>
        <SystemStatusProvider>
          <AppShell>{children}</AppShell>
        </SystemStatusProvider>
      </StreamProvider>
    </SessionProvider>
  );
}
