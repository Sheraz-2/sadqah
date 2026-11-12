"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import type { ColDef } from "ag-grid-community";
import { get } from "@/lib/api";
import { formatDate, formatUsd } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { DataGrid } from "@/components/grids/DataGrid";
import { Alert } from "@/components/ui/Alert";
import type { KycCase } from "@/types/admin";

export default function KycQueue() {
  const router = useRouter();
  const q = useAsync((s) => get<{ items: KycCase[] }>("/admin/kyc/queue", s), []);
  const columns = useMemo<ColDef<KycCase>[]>(
    () => [
      { field: "status", headerName: "Status" },
      { headerName: "Applicant", valueGetter: (p) => (p.data ? p.data.recipient_id.slice(0, 8) : ""), flex: 1 },
      { field: "income_monthly_usd_cents", headerName: "AI income / month", valueFormatter: (p) => (p.value == null ? "unreadable" : formatUsd(Number(p.value), { cents: true })) },
      { field: "face_match", headerName: "Face match", valueFormatter: (p) => (p.value == null ? "n/a" : `${Math.round(Number(p.value) * 100)}%`) },
      { field: "fraud_risk", headerName: "Risk", valueFormatter: (p) => (p.value == null ? "n/a" : `${Math.round(Number(p.value) * 100)}%`) },
      { headerName: "Flags", valueGetter: (p) => (p.data ? p.data.flags.length : 0) },
      { field: "recommended_allocation_cents", headerName: "AI suggests", valueFormatter: (p) => (p.value == null ? "none" : formatUsd(Number(p.value))) },
      { field: "created_at", headerName: "Applied", valueFormatter: (p) => formatDate(String(p.value)) },
    ],
    [],
  );
  return (
    <div className="space-y-5">
      <h1 className="text-4xl font-bold">Verification queue</h1>
      <p className="max-w-2xl text-ink-soft">The AI only advises. Open a case, read the documents yourself, then decide.</p>
      {q.error && !q.data ? <Alert tone="bad">{q.error}</Alert> : <DataGrid<KycCase> label="Verification queue" rows={q.data?.items ?? null} loading={q.loading} columns={columns} rowId={(r) => r.recipient_id} paginate={20} emptyText="Nothing waiting. Well done." onRowClick={(r) => router.push(`/admin/kyc/${r.recipient_id}`)} />}
    </div>
  );
}
