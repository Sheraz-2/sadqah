"use client";

import { useState, type FormEvent } from "react";
import { ApiError, post } from "@/lib/api";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Select, Textarea } from "@/components/ui/Field";

const REASONS = [
  { v: "fake_or_misleading", t: "The story looks fake or misleading" },
  { v: "not_in_need", t: "This person does not seem to be in need" },
  { v: "impersonation", t: "Someone is pretending to be another person" },
  { v: "inappropriate", t: "Inappropriate content" },
  { v: "other", t: "Something else" },
];

/** "Report this campaign": works without an account. Goes to a SadQah reviewer, never to the recipient. */
export function ReportCampaign({ slug }: { slug: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("fake_or_misleading");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function send(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const r = await post<{ message: string }>(`/campaigns/${encodeURIComponent(slug)}/report`, { reason, details: details.trim() });
      setDone(r.message);
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Could not send your report. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function close() {
    setOpen(false);
    if (done) { setDone(null); setDetails(""); }
  }

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="text-sm font-medium text-ink-soft underline underline-offset-2 hover:text-lapis-900">
        Report this campaign
      </button>
      <Modal open={open} onClose={close} title="Report this campaign">
        {done ? (
          <div className="space-y-4">
            <Alert tone="ok">{done}</Alert>
            <Button onClick={close}>Close</Button>
          </div>
        ) : (
          <form onSubmit={send} className="space-y-4">
            <p className="text-ink-soft">A SadQah reviewer reads every report. The person is not told who reported.</p>
            <Select label="What is wrong?" value={reason} onChange={(e) => setReason(e.target.value)}>
              {REASONS.map((r) => <option key={r.v} value={r.v}>{r.t}</option>)}
            </Select>
            <Textarea label="Tell us more" hint={reason === "other" ? "Please write at least 10 characters." : "Optional. Do not include passwords or card numbers."} rows={4} maxLength={1000} value={details} onChange={(e) => setDetails(e.target.value)} />
            {err && <Alert tone="bad">{err}</Alert>}
            <div className="flex gap-2">
              <Button type="submit" loading={busy}>Send report</Button>
              <Button type="button" variant="secondary" onClick={close}>Cancel</Button>
            </div>
          </form>
        )}
      </Modal>
    </>
  );
}
