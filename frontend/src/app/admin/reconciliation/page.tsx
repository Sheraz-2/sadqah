"use client";

import { useMemo } from "react";
import type { ColDef } from "ag-grid-community";
import { get } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { DataGrid } from "@/components/grids/DataGrid";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import type { ReconRow } from "@/types/admin";

export default function ReconciliationPage() {
  const r = useAsync((s) => get<{ ok: boolean; items: ReconRow[] }>("/admin/reconciliation", s), []);
  const money = (p: { value: unknown }) => formatUsd(Number(p.value), { cents: true });
  const cols = useMemo<ColDef<ReconRow>[]>(() => [
    { headerName: "Check", width: 120, flex: 0, valueGetter: (p) => (p.data && (p.data.raised_mismatch || p.data.paid_out_mismatch) ? "MISMATCH" : "OK"), cellClass: "font-semibold" },
    { headerName: "Campaign", valueGetter: (p) => (p.data ? p.data.campaign_id.slice(0, 8) : "") },
    { field: "raised_cents", headerName: "Recorded raised", valueFormatter: money },
    { field: "donations_captured_cents", headerName: "Donations captured", valueFormatter: money },
    { field: "payout_queued_cents", headerName: "Queued", valueFormatter: money },
    { field: "payout_in_flight_cents", headerName: "In flight", valueFormatter: money },
    { field: "payout_unclaimed_cents", headerName: "Unclaimed", valueFormatter: money },
    { field: "payout_problem_cents", headerName: "Problem", valueFormatter: money },
    { field: "paid_out_cents", headerName: "Recorded delivered", valueFormatter: money },
    { field: "payout_delivered_cents", headerName: "Payouts succeeded", valueFormatter: money },
  ], []);
  const bad = (r.data?.items ?? []).filter((i) => i.raised_mismatch || i.paid_out_mismatch);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-4xl font-bold">Reconciliation</h1>
        <Button variant="secondary" onClick={() => void r.reload()}>Refresh</Button>
      </div>
      {r.error && !r.data ? <Alert tone="bad">{r.error}</Alert> : r.data && (
        r.data.ok
          ? <Alert tone="ok" title="OK: every campaign reconciles">Recorded totals match the donation and payout rows.</Alert>
          : <Alert tone="bad" title={`NOT OK: ${bad.length} campaign${bad.length === 1 ? "" : "s"} do not reconcile`}>Mismatched rows are marked below and listed first. Do not requeue or adjust anything until you know why.</Alert>
      )}
      <DataGrid<ReconRow> label="Reconciliation" rows={r.data?.items ?? null} loading={r.loading} columns={cols} rowId={(x) => x.campaign_id} paginate={25} emptyText="No campaigns yet." />
    </div>
  );
}
