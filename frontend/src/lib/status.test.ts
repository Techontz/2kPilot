import { describe, expect, it } from "vitest";
import { tradingStatus } from "@/test/fixtures";
import { deriveRobotStatus } from "./status";

describe("deriveRobotStatus", () => {
  it("reports the kill switch first, with its reason", () => {
    const robot = deriveRobotStatus(tradingStatus({ kill_switch_reason: "news" }));
    expect(robot).toMatchObject({ label: "Trading stopped", tone: "warning", detail: "news", running: false });
  });

  it("reports LIVE + hard lock as blocked even when the kill switch is released", () => {
    const robot = deriveRobotStatus(tradingStatus({ kill_switch_engaged: false, trading_mode: "LIVE" }));
    expect(robot.label).toBe("Blocked");
    expect(robot.running).toBe(false);
  });

  it("reports an offline engine as not running", () => {
    const robot = deriveRobotStatus(tradingStatus({ kill_switch_engaged: false }));
    expect(robot).toMatchObject({ label: "Robot offline", running: false });
  });
});
