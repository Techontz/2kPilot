import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resolveTab, SectionTabs } from "./SectionTabs";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/history",
  useSearchParams: () => new URLSearchParams(search),
}));

const TABS = [
  { value: "open", label: "Open", content: <p>open content</p> },
  { value: "closed", label: "Closed", content: <p>closed content</p> },
];

beforeEach(() => {
  replace.mockReset();
  search = "";
});

describe("SectionTabs", () => {
  it("falls back to the first tab for unknown values", () => {
    expect(resolveTab(TABS, null)).toBe("open");
    expect(resolveTab(TABS, "nope")).toBe("open");
    expect(resolveTab(TABS, "closed")).toBe("closed");
  });

  it("opens the tab named in ?tab= and mounts only that one", () => {
    search = "tab=closed";
    render(<SectionTabs title="History" tabs={TABS} />);
    expect(screen.getByRole("heading", { level: 1, name: "History" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Closed" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("closed content")).toBeInTheDocument();
    expect(screen.queryByText("open content")).not.toBeInTheDocument();
  });

  it("writes the selected tab to the URL (first tab = clean URL)", async () => {
    search = "tab=closed";
    render(<SectionTabs title="History" tabs={TABS} />);
    await userEvent.click(screen.getByRole("tab", { name: "Open" }));
    expect(replace).toHaveBeenCalledWith("/history", { scroll: false });
  });
});
