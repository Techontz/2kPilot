import { AppShell } from "@/components/layout/AppShell";
import { AppDataProvider } from "@/components/providers/AppDataProvider";
import { SessionProvider } from "@/components/providers/SessionProvider";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <SessionProvider>
      <AppDataProvider>
        <AppShell>{children}</AppShell>
      </AppDataProvider>
    </SessionProvider>
  );
}
