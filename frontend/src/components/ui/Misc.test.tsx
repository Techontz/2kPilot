import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EnvBadge, Meter } from "./Misc";

describe("status helpers", () => {
  it("LIVE environment badge is emphasised; PAPER is neutral", () => {
    render(<><EnvBadge env="LIVE" /><EnvBadge env="PAPER" /></>);
    expect(screen.getByText("LIVE").className).toContain("bg-live");
    expect(screen.getByText("PAPER").className).not.toContain("bg-live");
  });

  it("meter turns red at 90% of the limit", () => {
    render(<Meter label="Daily loss" used={1.9} limit={2} detail="1.9 of 2" />);
    const meter = screen.getByRole("meter", { name: "Daily loss" });
    expect(meter.firstElementChild?.className).toContain("bg-negative");
  });
});
