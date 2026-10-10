import { describe, expect, it } from "vitest";
import { tradingStatus } from "@/test/fixtures";
import { deriveRobotStatus, engineHealthView } from "./status";
import type { EngineSummary } from "./types";

describe("deriveRobotStatus", () => {
  it("reports the kill switch first, with its reason", () => {
    const robot = deriveRobotStatus(tradingStatus({ kill_switch_reason: "news" }));
    expect(robot).toMatchObject({ label: "Trading stopped", tone: "warning", detail: "news", running: false });
  });

  it("reports a platform halt above everything else", () => {
    const robot = deriveRobotStatus(tradingStatus({ kill_switch_engaged: false, engine_state: "running", platform_halted: true, platform_halt_reason: "maintenance" }));
    expect(robot).toMatchObject({ label: "Halted by admin", tone: "negative", detail: "maintenance", running: false });
  });

  it("reports LIVE + hard lock as blocked even when the kill switch is released", () => {
    const robot = deriveRobotStatus(tradingStatus({ kill_switch_engaged: false, trading_mode: "LIVE" }));
    expect(robot.label).toBe("Blocked");
    expect(robot.running).toBe(false);
  });

  it("without a server summary, a missing heartbeat is not called 'Engine offline'", () => {
    const robot = deriveRobotStatus(tradingStatus({ kill_switch_engaged: false }));
    expect(robot).toMatchObject({ label: "Supervisor not running", tone: "warning", running: false });
  });

  it("reports running and degraded engines", () => {
    expect(deriveRobotStatus(tradingStatus({ kill_switch_engaged: false, engine_state: "running" }))).toMatchObject({ label: "Running", running: true });
    expect(deriveRobotStatus(tradingStatus({ kill_switch_engaged: false, engine_state: "degraded" })).tone).toBe("warning");
  });
});

const summary = (over: Partial<EngineSummary>): EngineSummary => ({ code: "running", tone: "ok", label: "Engine running", message: "Automated trading is active.", trading_active: true, ...over });

describe("engineHealthView", () => {
  it("API healthy but supervisor disabled: online, trading disabled, calm", () => {
    const status = tradingStatus({ kill_switch_engaged: false, engine_summary: summary({
      code: "trading_disabled", tone: "info", label: "Engine online — automated trading disabled",
      message: "The engine is healthy, but automated trading is switched off on this server.", trading_active: false }) });
    expect(engineHealthView(status)).toMatchObject({ label: "Engine online — automated trading disabled", tone: "info", active: false, banner: true });
    expect(deriveRobotStatus(status)).toMatchObject({ label: "Engine online — automated trading disabled", running: false });
    expect(deriveRobotStatus(status).label).not.toMatch(/offline/i);
  });

  it("active supervisor: running, no banner", () => {
    const status = tradingStatus({ kill_switch_engaged: false, engine_state: "running", engine_summary: summary({}) });
    expect(engineHealthView(status)).toMatchObject({ active: true, banner: false, tone: "positive" });
    expect(deriveRobotStatus(status)).toMatchObject({ label: "Running", running: true });
  });

  it("stale heartbeat: a warning, not offline", () => {
    const status = tradingStatus({ kill_switch_engaged: false, engine_summary: summary({
      code: "supervisor_stale", tone: "warning", label: "Trading supervisor not responding", message: "No heartbeat since 10:00 UTC.", trading_active: false }) });
    expect(engineHealthView(status)).toMatchObject({ tone: "warning", active: false, banner: true });
    expect(deriveRobotStatus(status)).toMatchObject({ label: "Trading supervisor not responding", tone: "warning", running: false });
  });

  it("unreachable API: the only case called 'Engine offline'", () => {
    const status = tradingStatus({ kill_switch_engaged: false, engine_summary: summary({
      code: "engine_offline", tone: "error", label: "Engine offline", message: "The trading engine cannot be reached.", trading_active: false }) });
    expect(engineHealthView(status)).toMatchObject({ label: "Engine offline", tone: "negative", banner: true });
    expect(deriveRobotStatus(status)).toMatchObject({ label: "Engine offline", tone: "negative", running: false });
  });

  it("kill switches and the platform halt still take precedence", () => {
    const disabled = summary({ code: "trading_disabled", tone: "info", label: "Engine online — automated trading disabled", trading_active: false });
    expect(deriveRobotStatus(tradingStatus({ engine_summary: disabled })).label).toBe("Trading stopped");
    expect(deriveRobotStatus(tradingStatus({ platform_halted: true, engine_summary: disabled })).label).toBe("Halted by admin");
  });
});
