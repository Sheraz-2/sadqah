"use client";

import { useState } from "react";
import { ApiError, get, post } from "@/lib/api";
import { formatDate, formatUsd } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import type { PricedItem } from "@/types/assistant";

type Case = {
  id: string;
  recipient_name: string;
  business_type: string | null;
  region_admin1: string | null;
  country: string;
  currency: string | null;
  status: string;
  items: Partial<PricedItem>[];
  requested_total_cents: number;
  estimated_total_cents: number | null;
  approved_allocation_cents: number | null;
  kyc_status: string | null;
  explanation: string | null;
  hr_filter_status: string;
  priority_queue: "HIGH" | "MEDIUM" | "LOW";
  ai_result: { proof?: { flags_found?: string[]; notes_for_human_reviewer?: string }; pricing?: { flags?: string[] }; model?: string | null };
  has_proof: boolean;
  proof_mime: string | null;
  reviewer_note: string | null;
  created_at: string;
};

const PRIO = { HIGH: "bad", MEDIUM: "warn", LOW: "neutral" } as const;
const HR: Record<string, { t: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  PASSED: { t: "Proof looks relevant", tone: "ok" },
  FLAGGED_SUSPICIOUS: { t: "Proof flagged", tone: "warn" },
  FAILED_IRRELEVANT: { t: "Proof not relevant", tone: "bad" },
  NOT_CHECKED: { t: "Proof not checked by AI", tone: "neutral" },
};

export default function NeedsQueuePage() {
  const q = useAsync((s) => get<{ items: Case[] }>("/admin/needs", s), []);
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-bold">Needs checks</h1>
        <p className="mt-1 max-w-2xl text-ink-soft">Lists of needs sent by recipients, highest priority first. The AI result is advice only: you look at the proof and decide. Opening a proof is recorded in the audit log.</p>
      </div>
      {q.loading && !q.data ? <Spinner label="Loading the queue" /> : q.error && !q.data ? <Alert tone="bad">{q.error}</Alert> : !q.data?.items.length ? (
        <Alert tone="ok">Nothing is waiting.</Alert>
      ) : (
        <ul className="space-y-4">{q.data.items.map((c) => <li key={c.id}><CaseCard c={c} done={() => void q.reload()} /></li>)}</ul>
      )}
    </div>
  );
}

function CaseCard({ c, done }: { c: Case; done: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const hr = HR[c.hr_filter_status] ?? HR.NOT_CHECKED;
  const proof = c.ai_result?.proof;
  const flags = [...(proof?.flags_found ?? []).filter((f) => f !== "None"), ...(c.ai_result?.pricing?.flags ?? [])];

  async function decide(decision: "approved" | "declined" | "more_info") {
    setErr(null); setBusy(decision);
    try { await post(`/admin/needs/${c.id}/decision`, { decision, note: note.trim() }); done(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Could not save the decision."); setBusy(null); }
  }

  return (
    <Card className="space-y-3 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-xl font-semibold" dir="auto">{c.recipient_name}</h2>
        <Badge tone={PRIO[c.priority_queue]}>{c.priority_queue} priority</Badge>
        <Badge tone={hr.tone}>{hr.t}</Badge>
        {c.status === "more_info" && <Badge tone="warn">Waiting for recipient</Badge>}
      </div>
      <p className="text-sm text-ink-soft">
        {[c.business_type, c.region_admin1, c.country].filter(Boolean).join(" · ")} · sent {formatDate(c.created_at)} · identity check: {c.kyc_status ?? "none"}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-ink-soft"><tr><th className="py-1 pr-3">Item</th><th className="pr-3">Qty</th><th className="pr-3">Asked each</th><th className="pr-3">Typical range</th><th>Check</th></tr></thead>
          <tbody>
            {c.items.map((i, n) => (
              <tr key={n} className="border-t border-line align-top">
                <td className="py-1.5 pr-3" dir="auto">{i.name}</td>
                <td className="pr-3">{i.quantity}</td>
                <td className="pr-3">{i.asked_unit_price} {c.currency}</td>
                <td className="pr-3">{i.low != null && i.high != null ? `${i.low} to ${i.high}` : "no estimate"}</td>
                <td>{i.status ?? "-"}{i.flags?.length ? ` (${i.flags.join(", ").replace(/_/g, " ")})` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-sm">
        Asked ≈ {formatUsd(c.requested_total_cents)}{c.estimated_total_cents != null && <> · typical ≈ {formatUsd(c.estimated_total_cents)}</>}
        {c.approved_allocation_cents != null && <> · approved limit {formatUsd(c.approved_allocation_cents)}</>}
      </p>

      {c.explanation && <blockquote className="rounded-xl bg-lapis-50 p-3 text-ink" dir="auto">{c.explanation}</blockquote>}
      {flags.length > 0 && <Alert tone="warn" title="Flags">{flags.map((f) => f.replace(/_/g, " ")).join("; ")}</Alert>}
      {proof?.notes_for_human_reviewer && <p className="text-sm text-ink-soft"><strong>AI note:</strong> {proof.notes_for_human_reviewer}</p>}

      {c.has_proof && (
        <a href={`/api/v1/admin/needs/${c.id}/proof`} target="_blank" rel="noopener noreferrer" className="inline-flex font-semibold text-lapis-700 underline underline-offset-2">Open the proof ({c.proof_mime}) in a new tab</a>
      )}

      <Textarea label="Note to the recipient (they will see it)" rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      {err && <Alert tone="bad">{err}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void decide("approved")} loading={busy === "approved"} disabled={busy !== null}>Approve</Button>
        <Button variant="secondary" onClick={() => void decide("more_info")} loading={busy === "more_info"} disabled={busy !== null || !note.trim()}>Ask for more</Button>
        <Button variant="danger" onClick={() => void decide("declined")} loading={busy === "declined"} disabled={busy !== null || !note.trim()}>Decline</Button>
      </div>
      <p className="text-sm text-ink-soft">Asking for more or declining needs a note, so the person knows why.</p>
    </Card>
  );
}
