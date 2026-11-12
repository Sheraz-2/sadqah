"use client";

import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef } from "ag-grid-community";
import { useMemo } from "react";
import { Spinner } from "@/components/ui/Spinner";

// AG Grid (hackathon sponsor): registered once for the whole app.
ModuleRegistry.registerModules([AllCommunityModule]);

const sadqahTheme = themeQuartz.withParams({
  accentColor: "#1b4580",
  backgroundColor: "#ffffff",
  foregroundColor: "#0d1b2e",
  borderColor: "#d9e1e4",
  headerBackgroundColor: "#eef3fb",
  headerTextColor: "#0f2a52",
  headerFontWeight: 600,
  fontFamily: "inherit",
  fontSize: 15,
  rowHoverColor: "#f4f7f6",
  wrapperBorderRadius: 16,
});

type Props<T> = {
  rows: T[] | null;
  columns: ColDef<T>[];
  /** Stable row id, so refreshed data updates rows in place instead of re-rendering the whole grid. */
  rowId?: (row: T) => string;
  loading?: boolean;
  emptyText?: string;
  paginate?: number;
  onRowClick?: (row: T) => void;
  label: string;
};

/** One consistent AG Grid for leaderboard, donations, KYC queue, payouts and ledger. Auto height, sortable, filterable. */
export function DataGrid<T>({ rows, columns, rowId, loading, emptyText = "Nothing here yet.", paginate, onRowClick, label }: Props<T>) {
  const defaultColDef = useMemo<ColDef<T>>(() => ({ sortable: true, filter: true, resizable: true, minWidth: 90, flex: 1 }), []);
  if (rows === null && loading) return <Spinner label={`Loading ${label}`} />;
  return (
    <div role="region" aria-label={label}>
      <AgGridReact<T>
        theme={sadqahTheme}
        rowData={rows ?? []}
        columnDefs={columns}
        defaultColDef={defaultColDef}
        domLayout="autoHeight"
        getRowId={rowId ? (p: { data: T }) => rowId(p.data) : undefined}
        pagination={!!paginate}
        paginationPageSize={paginate}
        overlayNoRowsTemplate={`<span>${emptyText}</span>`}
        onRowClicked={onRowClick ? (e: { data?: T }) => e.data && onRowClick(e.data) : undefined}
      />
    </div>
  );
}
