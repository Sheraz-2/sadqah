"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { API_BASE, ApiError, get, post } from "@/lib/api";
import { formatDate, formatUsd, parseDollarsToCents } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { Spinner } from "@/components/ui/Spinner";
import { DOC_LABELS } from "@/types/recipient";
import type { KycCaseDetail } from "@/types/admin";

type Decision = "approved" | "rejected" | "suspended";

export default function KycCasePage() {
  const { id } = useParams<{ id: string }>();
  const c = useAsync((s) => get<KycCaseDetail>(`/admin/kyc/${encodeURIComponent(id)}`, s), [id]);
  if (c.loading && !c.data) return <Spinner label="Loading application" />;
  if (!c.data) return <Alert tone="bad">{c.error ?? "Could not load this application."} <Link href="/admin/kyc" className="font-semibold underline">Back to the queue</Link></Alert>;
  return <Case c={c.data} onDecided={() => void c.reload()} />;
}

function Case({ c, onDecided }: { c: KycCaseDetail; onDecided: () => void }) {
  return (
    <div className="space-y-8">
      <div>
        <Link href="/admin/kyc" className="text-lapis-700 underline">← Verification queue</Link>
        <h1 className="mt-2 text-4xl font-bold">Application {c.recipient_id.slice(0, 8)}</h1>
        <p className="text-ink-soft">Status <Badge tone="info">{c.status}</Badge> · applied {formatDate(c.created_at)}{c.assessed_at ? ` · assessed ${formatDate(c.assessed_at)}` : ""}</p>
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <Card>
          <h2 className="text-2xl font-semibold">What they declared</h2>
          <dl className="mt-3 grid grid-cols-[9rem_1fr] gap-x-3 gap-y-2">
            <dt className="text-ink-soft">Full name</dt><dd>{c.identity.full_name}</dd>
            <dt className="text-ink-soft">Date of birth</dt><dd>{c.identity.date_of_birth}</dd>
            <dt className="text-ink-soft">ID number</dt><dd className="font-mono">{c.identity.id_number_masked}</dd>
            <dt className="text-ink-soft">Address</dt><dd>{c.identity.address}</dd>
            <dt className="text-ink-soft">Issuing country</dt><dd>{c.identity.doc_country ?? "n/a"}</dd>
          </dl>
          <p className="mt-3 text-sm text-ink-soft">Compare these with the documents yourself: this is personal data, handle it accordingly.</p>
        </Card>

        <Card>
          <h2 className="text-2xl font-semibold">AI assessment <Badge className="ml-2">advice only</Badge></h2>
          <dl className="mt-3 grid grid-cols-[11rem_1fr] gap-x-3 gap-y-2">
            <dt className="text-ink-soft">Income per month</dt><dd>{c.income_monthly_usd_cents == null ? "could not read" : formatUsd(c.income_monthly_usd_cents, { cents: true })}</dd>
            <dt className="text-ink-soft">Face match</dt><dd>{c.face_match == null ? "not run" : `${Math.round(c.face_match * 100)}%`}</dd>
            <dt className="text-ink-soft">Fraud risk</dt><dd>{c.fraud_risk == null ? "n/a" : `${Math.round(c.fraud_risk * 100)}%`}</dd>
            <dt className="text-ink-soft">Suggested allocation</dt><dd>{c.recommended_allocation_cents == null ? "none" : formatUsd(c.recommended_allocation_cents)}</dd>
          </dl>
          {c.flags.length > 0 ? (
            <ul className="mt-4 space-y-2">
              {c.flags.map((f, i) => (
                <li key={i} className="flex gap-2"><Badge tone={f.severity === "critical" ? "bad" : f.severity === "warning" ? "warn" : "neutral"}>{f.severity}</Badge><span>{f.detail}</span></li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-ink-soft">No flags raised. That does not replace your own check.</p>
          )}
        </Card>
      </div>

      <Documents c={c} />
      <DecisionPanel c={c} onDecided={onDecided} />
    </div>
  );
}

function Documents({ c }: { c: KycCaseDetail }) {
  const [viewing, setViewing] = useState<{ url: string; mime: string; title: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Object URLs hold the decrypted file in memory: always release them.
  useEffect(() => () => { if (viewing) URL.revokeObjectURL(viewing.url); }, [viewing]);

  async function view(doc: KycCaseDetail["documents"][number]) {
    setBusy(doc.id);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/admin/kyc/documents/${encodeURIComponent(doc.id)}/content`, { credentials: "include", cache: "no-store" });
      if (!res.ok) {
        let message = "Could not open that document.";
        try { message = (await res.json())?.error?.message ?? message; } catch { /* not JSON */ }
        throw new Error(message);
      }
      setViewing({ url: URL.createObjectURL(await res.blob()), mime: doc.mime_type, title: DOC_LABELS[doc.doc_type] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open that document.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <h2 className="text-2xl font-semibold">Documents</h2>
      <Alert tone="info" className="mt-3">Every time you open a document, it is recorded in the audit log with your name.</Alert>
      {error && <Alert tone="bad" className="mt-3">{error}</Alert>}
      <ul className="mt-4 divide-y divide-line">
        {c.documents.length === 0 && <li className="py-3 text-ink-soft">No documents.</li>}
        {c.documents.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
            <span>
              <span className="font-semibold">{DOC_LABELS[d.doc_type]}</span>
              <span className="block text-sm text-ink-soft">{formatDate(d.uploaded_at)} · {(d.size_bytes / 1024).toFixed(0)} KB · scan: {d.scan_status}</span>
            </span>
            <Button size="sm" variant="secondary" loading={busy === d.id} onClick={() => void view(d)}>View</Button>
          </li>
        ))}
      </ul>
      <Modal open={!!viewing} onClose={() => setViewing(null)} title={viewing?.title ?? "Document"} wide>
        {viewing && (viewing.mime === "application/pdf" ? <iframe src={viewing.url} title={viewing.title} sandbox="" className="h-[70vh] w-full rounded-xl" /> : <img src={viewing.url} alt={viewing.title} className="max-h-[70vh] w-full rounded-xl object-contain" />)}
      </Modal>
    </Card>
  );
}

function DecisionPanel({ c, onDecided }: { c: KycCaseDetail; onDecided: () => void }) {
  const [decision, setDecision] = useState<Decision>("approved");
  const [income, setIncome] = useState(c.income_monthly_usd_cents != null ? String(c.income_monthly_usd_cents / 100) : "");
  const [allocation, setAllocation] = useState(c.recommended_allocation_cents != null ? String(c.recommended_allocation_cents / 100) : "");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const decidable = ["needs_human_review", "approved", "suspended"].includes(c.status);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await post(`/admin/kyc/${encodeURIComponent(c.recipient_id)}/decision`, {
        decision,
        verified_monthly_income_cents: decision === "approved" ? parseDollarsToCents(income) : undefined,
        approved_allocation_cents: decision === "approved" && allocation ? parseDollarsToCents(allocation) : undefined,
        reason: decision === "approved" ? undefined : reason,
      });
      setConfirm(false);
      setDone(`Decision recorded: ${decision}.`);
      onDecided();
    } catch (err) {
      setConfirm(false);
      setError(err instanceof ApiError ? err.fields ? Object.values(err.fields).join(" ") || err.message : err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (!decidable) return <Alert tone="info">This application cannot be decided right now (status: {c.status}).</Alert>;
  return (
    <Card>
      <h2 className="text-2xl font-semibold">Your decision</h2>
      <div role="radiogroup" aria-label="Decision" className="mt-4 flex flex-wrap gap-2">
        {(["approved", "rejected", "suspended"] as const).map((d) => (
          <button key={d} type="button" role="radio" aria-checked={decision === d} onClick={() => setDecision(d)} className={`h-10 rounded-full px-5 font-semibold capitalize ring-1 ring-inset ${decision === d ? (d === "approved" ? "bg-tile-700 text-white ring-tile-700" : "bg-pomegranate-600 text-white ring-pomegranate-600") : "bg-white ring-line"}`}>{d}</button>
        ))}
      </div>
      <div className="mt-5 space-y-4">
        {decision === "approved" ? (
          <>
            <Input label="Verified monthly income (USD)" inputMode="decimal" value={income} onChange={(e) => setIncome(e.target.value)} hint="The income YOU verified from the documents. Must be under $50." />
            <Input label="Approved allocation (USD)" inputMode="decimal" value={allocation} onChange={(e) => setAllocation(e.target.value)} hint="Leave empty to use the AI suggestion. Allowed range $50 to $500." />
          </>
        ) : (
          <Textarea label="Reason (shown to the applicant)" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} hint="Be specific and kind. At least 10 characters." />
        )}
        {error && <Alert tone="bad">{error}</Alert>}
        {done && <Alert tone="ok">{done}</Alert>}
        <Button disabled={decision === "approved" ? parseDollarsToCents(income) <= 0 && income.trim() !== "0" : reason.trim().length < 10} onClick={() => setConfirm(true)}>Review decision</Button>
      </div>
      <Modal open={confirm} onClose={() => setConfirm(false)} title={`Confirm: ${decision}`}>
        <p className="text-ink-soft">{decision === "approved" ? `The applicant will be able to publish a campaign for up to ${allocation ? formatUsd(parseDollarsToCents(allocation)) : "the AI-suggested amount"}.` : "The applicant will be told your reason."} This is recorded under your name.</p>
        <div className="mt-5 flex gap-3">
          <Button loading={busy} variant={decision === "approved" ? "primary" : "danger"} onClick={() => void submit()}>Confirm {decision}</Button>
          <Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
        </div>
      </Modal>
    </Card>
  );
}
