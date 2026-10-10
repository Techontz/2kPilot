import { AppShell } from "@/components/layout/AppShell";
import { TradingControlProvider } from "@/components/layout/TradingControls";
import { AppDataProvider } from "@/components/providers/AppDataProvider";
import { LiveProvider } from "@/components/providers/LiveProvider";
import { SessionProvider } from "@/components/providers/SessionProvider";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <SessionProvider>
      <LiveProvider>
        <AppDataProvider>
          <TradingControlProvider>
            <AppShell>{children}</AppShell>
          </TradingControlProvider>
        </AppDataProvider>
      </LiveProvider>
    </SessionProvider>
  );
}
