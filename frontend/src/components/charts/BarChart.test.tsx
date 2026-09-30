import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { BarChart } from "./BarChart";

describe("BarChart", () => {
  it("labels every bar with its value (colour is never the only cue)", async () => {
    render(<BarChart label="Monthly" format={(v) => `${v}`} bars={[{ label: "Jan", value: 10 }, { label: "Feb", value: -5 }]} />);
    expect(screen.getByRole("button", { name: "Jan: 10" })).toBeInTheDocument();
    await userEvent.hover(screen.getByRole("button", { name: "Feb: -5" }));
    expect(screen.getByText("-5")).toBeInTheDocument();
  });

  it("renders nothing without data", () => {
    const { container } = render(<BarChart label="x" format={String} bars={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
