import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  align?: "left" | "right";
  className?: string;
  hideBelow?: "sm" | "md" | "lg";
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[] | null;
  rowKey: (row: T) => string | number;
  loading?: boolean;
  error?: string | null;
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  caption?: string;
}

const HIDE = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell" };

/** Accessible table with built-in loading / empty / error states. */
export function DataTable<T>({ columns, rows, rowKey, loading, error, empty, onRowClick, caption }: DataTableProps<T>) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="border-b border-line text-xs text-fg-subtle">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={cn(
                  "px-4 py-2.5 font-medium whitespace-nowrap",
                  c.align === "right" && "text-right",
                  c.hideBelow && HIDE[c.hideBelow],
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows?.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={onRowClick ? (e) => e.key === "Enter" && onRowClick(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              className={cn(onRowClick && "cursor-pointer hover:bg-surface-raised/60 focus:bg-surface-raised/60")}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    "px-4 py-2.5 align-middle",
                    c.align === "right" && "num text-right",
                    c.hideBelow && HIDE[c.hideBelow],
                    c.className,
                  )}
                >
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {loading && !rows && <p className="px-4 py-6 text-sm text-fg-subtle">Loading…</p>}
      {error && <p className="px-4 py-6 text-sm text-negative">{error}</p>}
      {!loading && !error && rows?.length === 0 && (
        <div className="px-4 py-10 text-center text-sm text-fg-subtle">{empty ?? "Nothing here yet."}</div>
      )}
    </div>
  );
}
