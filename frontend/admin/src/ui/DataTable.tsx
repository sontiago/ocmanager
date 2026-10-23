import type { ReactNode } from "react";
import { useT } from "../i18n";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render(row: T): ReactNode;
  className?: string;
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey(row: T): string | number;
  loading?: boolean;
  error?: string | null;
  emptyText?: string;
  onRowClick?(row: T): void;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  emptyText,
  onRowClick,
}: Props<T>) {
  const { t } = useT();

  if (error) {
    return (
      <p role="alert" className="rounded-md border border-danger p-3 text-danger">
        {error}
      </p>
    );
  }
  if (loading && !rows) return <p className="p-3 text-muted">{t("common.loading")}</p>;

  return (
    <div className="overflow-x-auto rounded-md bg-surface shadow-card">
      <table className="w-full text-left">
        <thead className="border-b-2 border-border">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={`px-3 py-2 font-bold ${c.className ?? ""}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows?.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-6 text-center text-muted">
                {emptyText ?? t("common.empty")}
              </td>
            </tr>
          )}
          {rows?.map((row) => (
            <tr
              key={rowKey(row)}
              className={`border-t border-border odd:bg-black/[0.03] hover:bg-black/[0.06] ${onRowClick ? "cursor-pointer" : ""}`}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} className={`px-3 py-2 ${c.className ?? ""}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
