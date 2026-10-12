import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { groupMarkets, matchesMarket } from "@/lib/markets";
import type { Instrument } from "@/lib/types";
import { MarketPicker } from "./market-picker";

const inst = (name: string, description: string, category = "synthetic", extra: Partial<Instrument> = {}): Instrument => ({
  name, canonical: name, description, category, digits: 2, trade_allowed: true, market_open: true, ...extra,
});

// As Deriv's active_symbols reports them (a subset, out of order).
const DERIV = [
  inst("frxEURUSD", "EUR/USD", "forex"),
  inst("R_100", "Volatility 100 Index"),
  inst("1HZ75V", "Volatility 75 (1s) Index"),
  inst("R_10", "Volatility 10 Index"),
  inst("BOOM1000", "Boom 1000 Index"),
  inst("R_75", "Volatility 75 Index"),
  inst("1HZ10V", "Volatility 10 (1s) Index"),
  inst("R_25", "Volatility 25 Index"),
  inst("R_50", "Volatility 50 Index", "synthetic", { trade_allowed: false }),
];

describe("market grouping", () => {
  it("lists Volatility indices first, by level, apart from the 1s ones and other synthetics", () => {
    const groups = groupMarkets(DERIV);
    expect(groups.map((g) => g.label)).toEqual(["Volatility indices", "Volatility indices (1s)", "Other synthetic indices", "Forex"]);
    expect(groups[0]!.instruments.map((i) => i.name)).toEqual(["R_10", "R_25", "R_50", "R_75", "R_100"]);
    expect(groups[1]!.instruments.map((i) => i.name)).toEqual(["1HZ10V", "1HZ75V"]);
  });

  it("finds markets by name, Deriv code or shorthand", () => {
    const names = (q: string) => DERIV.filter((i) => matchesMarket(i, q)).map((i) => i.name);
    expect(names("volatility 75")).toEqual(["1HZ75V", "R_75"]);
    expect(names("v75 1s")).toEqual(["1HZ75V"]);
    expect(names("r_100")).toEqual(["R_100"]);
    expect(names("eur")).toEqual(["frxEURUSD"]);
  });

  it("never invents a Volatility index from the name alone in other categories", () => {
    expect(groupMarkets([inst("X", "Volatility 75 Index", "indices")]).map((g) => g.key)).toEqual(["indices"]);
  });
});

describe("MarketPicker", () => {
  it("filters as you type and picks with the keyboard", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MarketPicker instruments={DERIV} value="" onChange={onChange} />);
    await user.type(screen.getByRole("combobox"), "volatility 25");
    const list = screen.getByRole("listbox");
    expect(within(list).getAllByRole("option")).toHaveLength(1);
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("R_25");
  });

  it("explains suspended markets and won't pick them", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MarketPicker instruments={DERIV} value="" onChange={onChange} />);
    const suspended = screen.getByRole("option", { name: /Volatility 50 Index/ });
    expect(suspended).toHaveAttribute("aria-disabled", "true");
    expect(suspended).toHaveTextContent("Suspended by the broker");
    await user.click(suspended);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("says why the list is empty and offers a refresh", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(<MarketPicker instruments={[]} value="" onChange={() => {}} error="Deriv did not answer in time" onRefresh={onRefresh} />);
    expect(screen.getByText(/Couldn't load markets from the broker/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Fetch markets from the broker again/ }));
    expect(onRefresh).toHaveBeenCalled();
  });
});
