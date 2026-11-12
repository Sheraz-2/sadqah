"use client";

import { useMemo, useState } from "react";
import type { ColDef } from "ag-grid-community";
import { ApiError, get, post } from "@/lib/api";
import { formatDate, formatUsd } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { useAuth } from "@/hooks/useAuth";
import { DataGrid } from "@/components/grids/DataGrid";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { Select } from "@/components/ui/Field";
import type { Batch, PayoutItem } from "@/types/admin";

const STATUSES = ["queued", "batched", "submitted", "succeeded", "unclaimed", "returned", "failed", "blocked", "held", "cancelled"];
const REQUEUEABLE = ["failed", "blocked"];

function whenText(iso: string | null): string {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(d);
}

/** Why a queued payout has not been sent yet. Only queued rows have an answer; the server decides it from real data. */
function eligibilityLabel(p: Pick<PayoutItem, "eligibility">): string {
  if (p.eligibility === "ready") return "Ready";
  if (p.eligibility === "waiting") return "Waiting";
  if (p.eligibility === "kyc_blocked") return "Blocked: KYC not approved";
  return "";
}

function eligibilityExplanation(p: Pick<PayoutItem, "eligibility" | "next_attempt_at">): string {
  if (p.eligibility === "ready") return "Eligible now. It is sent when the next batch fires (enough ready payouts, or the oldest has waited long enough).";
  if (p.eligibility === "waiting") return `Scheduled for ${whenText(p.next_attempt_at)}. The payout worker will not pick it up before then.`;
  if (p.eligibility === "kyc_blocked") return "The recipient's KYC is not approved, so the payout worker skips this payout until it is.";
  return "";
}

export default function PayoutsPage() {
  const { me } = useAuth();
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<PayoutItem | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  const batches = useAsync((s) => get<{ items: Batch[] }>("/admin/payouts/batches?limit=50", s), []);
  const queue = useAsync((s) => get<{ items: PayoutItem[] }>(`/admin/payouts/queue?limit=200${status ? `&status=${status}` : ""}`, s), [status]);

  const batchCols = useMemo<ColDef<Batch>[]>(() => [
    { field: "sender_batch_id", headerName: "Batch", flex: 2 },
    { field: "status", headerName: "Status" },
    { field: "item_count", headerName: "Items" },
    { field: "total_cents", headerName: "Total", valueFormatter: (p) => formatUsd(Number(p.value), { cents: true }) },
    { field: "attempt_count", headerName: "Tries" },
    { field: "last_error", headerName: "Last error", flex: 2, valueFormatter: (p) => (p.value ? String(p.value) : "") },
    { field: "created_at", headerName: "Created", valueFormatter: (p) => formatDate(String(p.value)) },
  ], []);
  const queueCols = useMemo<ColDef<PayoutItem>[]>(() => [
    { headerName: "Payout", valueGetter: (p) => (p.data ? p.data.id.slice(0, 8) : "") },
    { field: "amount_cents", headerName: "Amount", valueFormatter: (p) => formatUsd(Number(p.value), { cents: true }), filter: "agNumberColumnFilter" },
    { field: "status", headerName: "Status" },
    { headerName: "Eligibility", valueGetter: (p) => (p.data ? eligibilityLabel(p.data) : "") },
    { field: "next_attempt_at", headerName: "Eligible from", valueFormatter: (p) => whenText(p.value ? String(p.value) : null) },
    { field: "paypal_transaction_status", headerName: "PayPal says", valueFormatter: (p) => (p.value ? String(p.value) : "") },
    { field: "failure_reason", headerName: "Reason", flex: 2, valueFormatter: (p) => (p.value ? String(p.value) : "") },
    { field: "queued_at", headerName: "Queued", valueFormatter: (p) => formatDate(String(p.value)) },
  ], []);

  async function requeue() {
    if (!selected) return;
    setBusy(true);
    setMsg(null);
    try {
      await post(`/admin/payouts/${selected.id}/requeue`);
      setMsg({ tone: "ok", text: "Payout requeued. The next batch will pick it up." });
      setSelected(null);
      void queue.reload();
    } catch (err) {
      setMsg({ tone: "bad", text: err instanceof ApiError ? err.message : "Could not requeue." });
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  }

  return (
    <div className="space-y-10">
      <h1 className="text-4xl font-bold">Payouts</h1>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}

      <section aria-labelledby="b-h">
        <h2 id="b-h" className="text-2xl font-semibold">Batches</h2>
        <div className="mt-3"><DataGrid<Batch> label="Payout batches" rows={batches.data?.items ?? null} loading={batches.loading} columns={batchCols} rowId={(r) => r.id} paginate={10} emptyText="No batches yet." /></div>
      </section>

      <section aria-labelledby="q-h">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="q-h" className="text-2xl font-semibold">Payout queue</h2>
          <Select label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-48">
            <option value="">All</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </div>
        <div className="mt-3"><DataGrid<PayoutItem> label="Payout queue" rows={queue.data?.items ?? null} loading={queue.loading} columns={queueCols} rowId={(r) => r.id} paginate={15} emptyText="Nothing in the queue." onRowClick={setSelected} /></div>
        {selected && (
          <Card className="mt-4">
            <p className="font-semibold">Payout {selected.id.slice(0, 8)} · {formatUsd(selected.amount_cents, { cents: true })} <Badge tone={REQUEUEABLE.includes(selected.status) ? "bad" : "neutral"}>{selected.status}</Badge></p>
            {selected.eligibility && <p className="mt-1 text-ink-soft"><span className="font-semibold">{eligibilityLabel(selected)}.</span> {eligibilityExplanation(selected)}</p>}
            {selected.failure_reason && <p className="mt-1 text-ink-soft">{selected.failure_reason}</p>}
            {me?.role === "admin" && REQUEUEABLE.includes(selected.status) ? (
              <Button className="mt-3" variant="secondary" onClick={() => setConfirm(true)}>Requeue this payout</Button>
            ) : REQUEUEABLE.includes(selected.status) ? (
              <p className="mt-2 text-sm text-ink-soft">Only an administrator can requeue payouts.</p>
            ) : null}
          </Card>
        )}
      </section>

      <Modal open={confirm} onClose={() => setConfirm(false)} title="Requeue this payout?">
        <p className="text-ink-soft">It goes back to the queue and will be included in the next batch. Check the failure reason first: requeueing a payout PayPal blocked for a real reason will fail again.</p>
        <div className="mt-5 flex gap-3">
          <Button loading={busy} onClick={() => void requeue()}>Requeue</Button>
          <Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
        </div>
      </Modal>
    </div>
  );
}
