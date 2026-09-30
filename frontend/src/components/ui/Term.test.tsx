import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { GLOSSARY } from "@/lib/glossary";
import { Term } from "./Term";

describe("Term", () => {
  it("explains the term on keyboard focus and hides it on Escape", async () => {
    const user = userEvent.setup();
    render(<Term id="equity" />);
    expect(screen.queryByRole("tooltip")).toBeNull();
    await user.tab();
    expect(screen.getByRole("tooltip")).toHaveTextContent(GLOSSARY.equity.definition);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("covers every term the product brief requires", () => {
    const required = [
      "balance", "equity", "margin", "freeMargin", "pip", "lot", "spread", "drawdown",
      "riskReward", "stopLoss", "takeProfit", "profitFactor", "expectancy",
    ];
    expect(Object.keys(GLOSSARY)).toEqual(expect.arrayContaining(required));
  });
});
