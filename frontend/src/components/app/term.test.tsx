import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GLOSSARY } from "@/lib/glossary";
import { Term } from "./term";

describe("Term", () => {
  it("explains the term on keyboard focus and hides it on Escape", async () => {
    const user = userEvent.setup();
    render(<TooltipProvider delayDuration={0}><Term id="stake" /></TooltipProvider>);
    expect(screen.queryByRole("tooltip")).toBeNull();
    await user.tab();
    expect(await screen.findByRole("tooltip")).toHaveTextContent(GLOSSARY.stake.definition);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("covers every term the product needs", () => {
    const required = [
      "balance", "equity", "drawdown", "profitFactor", "expectancy", "stake", "payout",
      "riseFall", "multiplier", "winRate", "losingStreak", "realizedPnl", "killSwitch",
    ];
    expect(Object.keys(GLOSSARY)).toEqual(expect.arrayContaining(required));
  });
});
