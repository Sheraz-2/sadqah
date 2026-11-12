"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError, get, post } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";

type Report = { id: string; reason: string; details: string; status: string; campaign_slug: string; campaign_title: string; campaign_status: string; recipient_id: string; reports_on_campaign: number; created_at: string };

const REASON: Record<string, string> = {
  fake_or_misleading: "Fake or misleading",
  not_in_need: "Does not seem to be in need",
  impersonation: "Pretending to be someone else",
  inappropriate: "Inappropriate content",
  other: "Something else",
};

export default function ReportsPage() {
  const q = useAsync((s) => get<{ items: Report[] }>("/admin/reports", s), []);
  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-bold">Reports from the public</h1>
        <p className="mt-1 max-w-2xl text-ink-soft">Campaigns with the most reports come first. &ldquo;Actioned&rdquo; records that you acted on it. To stop a campaign, suspend the person in Verification.</p>
      </div>
      {q.loading && !q.data ? <Spinner label="Loading reports" /> : q.error && !q.data ? <Alert tone="bad">{q.error}</Alert> : !q.data?.items.length ? (
        <Alert tone="ok">No open reports.</Alert>
      ) : (
        <ul className="space-y-3">{q.data.items.map((r) => <li key={r.id}><Row r={r} done={() => void q.reload()} /></li>)}</ul>
      )}
    </div>
  );
}

function Row({ r, done }: { r: Report; done: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function resolve(status: "dismissed" | "actioned") {
    setBusy(status); setErr(null);
    try { await post(`/admin/reports/${r.id}/resolve`, { status }); done(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Could not save."); setBusy(null); }
  }
  return (
    <Card className="space-y-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={`/campaigns/${r.campaign_slug}`} className="text-lg font-semibold text-lapis-700 underline underline-offset-2" dir="auto">{r.campaign_title}</Link>
        <Badge tone={r.reports_on_campaign > 2 ? "bad" : "warn"}>{r.reports_on_campaign} open report{r.reports_on_campaign === 1 ? "" : "s"}</Badge>
        <Badge>{r.campaign_status}</Badge>
      </div>
      <p><strong>{REASON[r.reason] ?? r.reason}</strong> · {formatDate(r.created_at)}</p>
      {r.details && <blockquote className="rounded-xl bg-lapis-50 p-3" dir="auto">{r.details}</blockquote>}
      {err && <Alert tone="bad">{err}</Alert>}
      <div className="flex gap-2">
        <Button size="sm" onClick={() => void resolve("actioned")} loading={busy === "actioned"} disabled={busy !== null}>Actioned</Button>
        <Button size="sm" variant="secondary" onClick={() => void resolve("dismissed")} loading={busy === "dismissed"} disabled={busy !== null}>Dismiss</Button>
      </div>
    </Card>
  );
}
