import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveBanner } from "./LiveBanner";
import { ModeBadge } from "./ModeBadge";

describe("LIVE indicators", () => {
  it("shows a persistent alert banner only in LIVE mode", () => {
    const { rerender } = render(<LiveBanner mode="DEMO" />);
    expect(screen.queryByRole("alert")).toBeNull();
    rerender(<LiveBanner mode="LIVE" />);
    expect(screen.getByRole("alert")).toHaveTextContent(/real money/i);
  });

  it("labels the mode badge for screen readers", () => {
    render(<ModeBadge mode="DEMO" />);
    expect(screen.getByText(/operating mode/i).parentElement).toHaveTextContent("Demo");
  });
});
