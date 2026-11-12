"use client";

import { useState, type FormEvent } from "react";
import { ApiError, get, post } from "@/lib/api";
import { formatDate, formatUsd } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { RecipientShell } from "@/components/recipient/RecipientNav";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import type { RecipientDonation } from "@/types/recipient";

export default function ThanksPage() {
  return (
    <RecipientShell title="Thank-yous" intro="Say thank you for each gift that reached you. A public donor receives it directly; an anonymous donor is thanked as part of the community.">
      {() => <List />}
    </RecipientShell>
  );
}

function List() {
  const gifts = useAsync((s) => get<{ items: RecipientDonation[] }>("/recipient/donations", s), []);
  if (gifts.loading && !gifts.data) return <Spinner label="Loading gifts" />;
  if (gifts.error && !gifts.data) return <Alert tone="bad">We could not load your gifts.</Alert>;
  const delivered = (gifts.data?.items ?? []).filter((g) => g.delivery_state === "delivered");
  if (delivered.length === 0) return <Alert tone="info">You can thank a donor once their gift has been delivered. Nothing to thank yet.</Alert>;
  return (
    <ul className="space-y-4">
      {delivered.map((g) => (
        <li key={g.donation_id}>
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold">{formatUsd(g.amount_cents)} from {g.donor_label}</p>
              <span className="text-sm text-ink-soft">{formatDate(g.paid_out_at ?? g.captured_at)}</span>
            </div>
            {g.has_gratitude ? <Badge tone="ok" className="mt-2">Thanked</Badge> : <ThankForm id={g.donation_id} onDone={() => void gifts.reload()} />}
          </Card>
        </li>
      ))}
    </ul>
  );
}

function ThankForm({ id, onDone }: { id: string; onDone: () => void }) {
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await post<{ id: string; audience: "donor" | "community"; status: "approved" | "pending" }>("/recipient/gratitude", { donation_id: id, body });
      setSent(res.status === "approved" ? "Your thank-you is on its way." : "Your thank-you was sent and will appear once it has been reviewed.");
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.fields?.body ?? err.message : "Could not send. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) return <Alert tone="ok" className="mt-3">{sent}</Alert>;
  return (
    <form onSubmit={submit} className="mt-3 space-y-3">
      <Textarea label="Your thank-you" rows={3} maxLength={1000} value={body} onChange={(e) => setBody(e.target.value)} error={error} hint="Please do not include phone numbers, e-mail addresses or links." />
      <Button type="submit" size="sm" loading={busy} disabled={!body.trim()}>Send thank-you</Button>
    </form>
  );
}
