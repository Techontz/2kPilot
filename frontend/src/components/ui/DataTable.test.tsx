import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DataTable } from "./DataTable";

const columns = [{ key: "a", header: "Name", cell: (r: { id: number; name: string }) => r.name }];

describe("DataTable", () => {
  it("shows loading, empty and error states", () => {
    const { rerender } = render(<DataTable columns={columns} rows={null} loading rowKey={(r) => r.id} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    rerender(<DataTable columns={columns} rows={[]} rowKey={(r) => r.id} empty="No trades." />);
    expect(screen.getByText("No trades.")).toBeInTheDocument();
    rerender(<DataTable columns={columns} rows={[]} rowKey={(r) => r.id} error="Boom" />);
    expect(screen.getByText("Boom")).toBeInTheDocument();
  });

  it("rows are keyboard-activatable when clickable", async () => {
    const onRowClick = vi.fn();
    render(<DataTable columns={columns} rows={[{ id: 1, name: "EURUSD" }]} rowKey={(r) => r.id} onRowClick={onRowClick} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledWith({ id: 1, name: "EURUSD" });
  });
});
