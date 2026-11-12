"use client";

import { useEffect, useMemo, useState } from "react";
import type { ColDef } from "ag-grid-community";
import { ApiError, get } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { DataGrid } from "@/components/grids/DataGrid";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { LedgerEvent } from "@/types/admin";

const PAGE = 200;

/** Append-only money ledger, newest first. "Load older" continues after the last id shown. */
export default function LedgerPage() {
  const [rows, setRows] = useState<LedgerEvent[]>([]);
  const [more, setMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<LedgerEvent | null>(null);

  async function load(after?: number) {
    setLoading(true);
    setError(null);
    try {
      const res = await get<{ items: LedgerEvent[] }>(`/admin/ledger?limit=${PAGE}${after ? `&after_id=${after}` : ""}`);
      setRows((prev) => (after ? [...prev, ...res.items] : res.items));
      setMore(res.items.length === PAGE);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the ledger.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { void load(); }, []);

  const cols = useMemo<ColDef<LedgerEvent>[]>(() => [
    { field: "id", headerName: "#", width: 90, flex: 0, filter: "agNumberColumnFilter" },
    { field: "event_type", headerName: "Event", flex: 2 },
    { field: "amount_cents", headerName: "Amount", valueFormatter: (p) => (p.value == null ? "n/a" : formatUsd(Number(p.value), { cents: true })), filter: "agNumberColumnFilter" },
    { field: "source", headerName: "Source", valueFormatter: (p) => (p.value ? String(p.value) : "") },
    { field: "created_at", headerName: "When", flex: 2, valueFormatter: (p) => new Date(String(p.value)).toLocaleString() },
  ], []);

  return (
    <div className="space-y-5">
      <h1 className="text-4xl font-bold">Ledger</h1>
      <p className="max-w-2xl text-ink-soft">Every money event, recorded once and never changed. Click a row for its details.</p>
      {error && <Alert tone="bad">{error}</Alert>}
      <DataGrid<LedgerEvent> label="Ledger" rows={loading && rows.length === 0 ? null : rows} loading={loading} columns={cols} rowId={(r) => String(r.id)} paginate={25} emptyText="No events yet." onRowClick={setOpen} />
      {open && (
        <Card>
          <h2 className="text-xl font-semibold">Event #{open.id}: {open.event_type}</h2>
          <dl className="mt-3 grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 break-all text-sm">
            {(["donation_id", "payout_queue_id", "batch_id", "recipient_id", "external_event_id"] as const).map((k) => (
              <div key={k} className="contents"><dt className="text-ink-soft">{k}</dt><dd className="font-mono">{open[k] ?? "n/a"}</dd></div>
            ))}
          </dl>
          <pre className="mt-3 overflow-x-auto rounded-xl bg-lapis-50 p-3 text-sm">{JSON.stringify(open.details, null, 2)}</pre>
        </Card>
      )}
      {more && rows.length > 0 && <Button variant="secondary" loading={loading} onClick={() => void load(rows[rows.length - 1].id)}>Load older events</Button>}
    </div>
  );
}
