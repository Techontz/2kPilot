import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { tradingStatus } from "@/test/fixtures";
import type { EngineSummary, TradingStatus } from "@/lib/types";
import { EnvironmentStrip } from "./EnvironmentStrip";

let status: TradingStatus | null = null;
vi.mock("../providers/AppDataProvider", () => ({ useAppData: () => ({ account: null, status }) }));
vi.mock("../providers/SessionProvider", () => ({ useSession: () => ({ user: { mfa_enabled: true } }) }));

const summary = (over: Partial<EngineSummary>): EngineSummary => ({ code: "running", tone: "ok", label: "Engine running", message: "Automated trading is active.", trading_active: true, ...over });

describe("EnvironmentStrip engine banner", () => {
  beforeEach(() => { status = null; });

  it("disabled supervisor: says the engine is online, not offline", () => {
    status = tradingStatus({ kill_switch_engaged: false, engine_summary: summary({ code: "trading_disabled", tone: "info", label: "Engine online — automated trading disabled", message: "No strategy will open trades.", trading_active: false }) });
    render(<EnvironmentStrip />);
    expect(screen.getByRole("status")).toHaveTextContent("Engine online — automated trading disabled");
    expect(screen.queryByText(/engine is offline/i)).toBeNull();
    expect(screen.queryByText(/make dev/i)).toBeNull();
  });

  it("stale supervisor: a warning banner", () => {
    status = tradingStatus({ engine_summary: summary({ code: "supervisor_stale", tone: "warning", label: "Trading supervisor not responding", message: "No heartbeat since 10:00 UTC.", trading_active: false }) });
    render(<EnvironmentStrip />);
    expect(screen.getByRole("status")).toHaveTextContent("Trading supervisor not responding");
  });

  it("unreachable API: an alert saying Engine offline", () => {
    status = tradingStatus({ engine_summary: summary({ code: "engine_offline", tone: "error", label: "Engine offline", message: "The trading engine cannot be reached.", trading_active: false }) });
    render(<EnvironmentStrip />);
    expect(screen.getByRole("alert")).toHaveTextContent("Engine offline");
  });

  it("running supervisor: no engine banner", () => {
    status = tradingStatus({ engine_state: "running", engine_summary: summary({}) });
    const { container } = render(<EnvironmentStrip />);
    expect(container).toBeEmptyDOMElement();
  });
});
