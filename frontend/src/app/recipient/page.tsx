"use client";

import Link from "next/link";
import { useMemo } from "react";
import type { ColDef } from "ag-grid-community";
import { get } from "@/lib/api";
import { formatDate, formatUsd, timeAgo } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { RecipientShell } from "@/components/recipient/RecipientNav";
import { DataGrid } from "@/components/grids/DataGrid";
import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";
import { Card } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/ProgressBar";
import type { RecipientMe } from "@/types/api";
import type { KindWord, RecipientDonation } from "@/types/recipient";

const DELIVERY: Record<string, string> = {
  queued_for_next_batch: "Waiting for the next payout batch",
  being_prepared: "Being prepared",
  on_its_way: "On its way to PayPal",
  awaiting_recipient_claim: "Waiting for you to claim it in PayPal",
  delivered: "Delivered",
  needs_attention: "Needs attention",
};

function nextStep(rme: RecipientMe): { tone: "info" | "ok" | "warn" | "bad"; title: string; body: string; href?: string; cta?: string } {
  if (!rme.profile) return { tone: "info", title: "Start with your profile", body: "Tell donors your first name, your small business and where you are, and add the PayPal e-mail where your gifts should go.", href: "/recipient/profile", cta: "Create my profile" };
  const k = rme.kyc;
  if (!k || k.status === "not_started" || k.status === "documents_pending")
    return { tone: "info", title: "Complete your verification", body: k && k.missing.length ? `Still needed: ${k.missing.length} item${k.missing.length === 1 ? "" : "s"}. Every recipient is verified so donors can trust the gifts.` : "Review your details and submit for verification.", href: "/recipient/verify", cta: "Continue verification" };
  if (k.status === "processing") return { tone: "info", title: "We are reading your documents", body: "This usually takes a few minutes. A human reviewer then makes the final decision. You do not need to do anything." };
  if (k.status === "needs_human_review") return { tone: "info", title: "A reviewer is looking at your application", body: "A person on our team makes the final decision. We will show the result here." };
  if (k.status === "rejected") return { tone: "bad", title: "Your application was not approved", body: k.rejection_reason ?? "Please check your details and documents.", href: "/recipient/verify", cta: "Fix and resubmit" };
  if (k.status === "suspended") return { tone: "bad", title: "Your account is paused", body: k.rejection_reason ?? "Please contact SadQah support.", };
  if (!rme.campaign) return { tone: "ok", title: "You are verified", body: `You can ask for up to ${formatUsd(k.approved_allocation_cents ?? 0)}. Create your campaign so donors can find you.`, href: "/recipient/campaign", cta: "Create my campaign" };
  if (!rme.profile.profile_public) return { tone: "warn", title: "Make your profile public", body: "Your campaign is ready, but donors cannot see it until you publish your profile.", href: "/recipient/profile", cta: "Publish my profile" };
  return { tone: "ok", title: "Your campaign is live", body: "Post an update with photos to show donors how their gifts are helping.", href: "/recipient/campaign", cta: "Post an update" };
}

export default function RecipientHome() {
  return (
    <RecipientShell title="Your portal" intro="Everything about your profile, verification and gifts in one place.">
      {({ rme }) => <Overview rme={rme} />}
    </RecipientShell>
  );
}

function Overview({ rme }: { rme: RecipientMe }) {
  const step = nextStep(rme);
  const gifts = useAsync((s) => get<{ items: RecipientDonation[] }>("/recipient/donations", s), []);
  const b = rme.balance;
  const c = rme.campaign;
  const columns = useMemo<ColDef<RecipientDonation>[]>(
    () => [
      { field: "donor_label", headerName: "From", flex: 2 },
      { field: "amount_cents", headerName: "Amount", valueFormatter: (p) => formatUsd(Number(p.value)), filter: "agNumberColumnFilter" },
      { field: "delivery_state", headerName: "Where it is", flex: 2, valueFormatter: (p) => DELIVERY[String(p.value)] ?? String(p.value) },
      { field: "captured_at", headerName: "Given", valueFormatter: (p) => formatDate(String(p.value)) },
    ],
    [],
  );

  return (
    <div className="space-y-10">
      <Alert tone={step.tone} title={step.title}>
        <p>{step.body}</p>
        {step.href && step.cta && <LinkButton href={step.href} size="sm" className="mt-3">{step.cta}</LinkButton>}
      </Alert>

      {c && (
        <Card>
          <h2 className="text-2xl font-semibold">{c.title}</h2>
          <p className="mt-1 text-ink-soft">{formatUsd(c.raised_cents)} raised of {formatUsd(c.goal_cents)}</p>
          <ProgressBar className="mt-3" percent={c.goal_cents ? (c.raised_cents / c.goal_cents) * 100 : 0} />
        </Card>
      )}

      {b && (
        <section aria-labelledby="bal-h">
          <h2 id="bal-h" className="text-3xl font-semibold">Where the money is</h2>
          <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Money label="Given to you in total" cents={b.raised_cents} />
            <Money label="Waiting for the next batch" cents={b.queued_cents} />
            <Money label="On its way to you" cents={b.in_flight_cents} />
            <Money label="Waiting for you to claim in PayPal" cents={b.unclaimed_cents} tone={b.unclaimed_cents > 0 ? "warn" : undefined} />
            <Money label="In your PayPal account" cents={b.delivered_cents} tone="ok" />
            <Money label="Needs attention" cents={b.problem_cents} tone={b.problem_cents > 0 ? "bad" : undefined} />
          </dl>
          {b.unclaimed_cents > 0 && <p className="mt-3 text-ink-soft">If your PayPal e-mail has no PayPal account yet, PayPal sends an invitation to claim the money. <Link href="/recipient/profile" className="underline">Check your payout e-mail</Link>.</p>}
        </section>
      )}

      <section aria-labelledby="gifts-h">
        <h2 id="gifts-h" className="text-3xl font-semibold">Gifts to you</h2>
        <div className="mt-4">
          <DataGrid<RecipientDonation> label="Gifts to you" rows={gifts.data?.items ?? null} loading={gifts.loading} columns={columns} rowId={(r) => r.donation_id} paginate={10} emptyText="No gifts yet." />
        </div>
      </section>

      <KindWords />
    </div>
  );
}

/** Approved public comments on the recipient's own campaign(s), newest first. Private messages live under Messages. */
function KindWords() {
  const words = useAsync((s) => get<{ items: KindWord[] }>("/recipient/kind-words", s), []);
  const items = words.data?.items ?? [];
  return (
    <section aria-labelledby="kind-h">
      <h2 id="kind-h" className="text-3xl font-semibold">Kind words</h2>
      <p className="mt-1 text-ink-soft">Public comments people have left on your campaign. They are the same words visitors see on your campaign page.</p>
      <div className="mt-4">
        {words.loading && !words.data ? (
          <Spinner label="Loading kind words" />
        ) : words.error && !words.data ? (
          <Alert tone="bad">We could not load your kind words. Please refresh.</Alert>
        ) : items.length === 0 ? (
          <p className="text-ink-soft">No kind words yet. When someone leaves a comment on your campaign, it will appear here.</p>
        ) : (
          <ul className="space-y-3">
            {items.map((w) => (
              <li key={w.id} className="rounded-2xl bg-saffron-100 p-5">
                <p className="whitespace-pre-wrap break-words">{w.body}</p>
                <p className="mt-2 text-sm text-ink-soft">{w.author_name} · {timeAgo(w.created_at)}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Money({ label, cents, tone }: { label: string; cents: number; tone?: "ok" | "warn" | "bad" }) {
  const color = tone === "ok" ? "text-tile-700" : tone === "warn" ? "text-saffron-600" : tone === "bad" ? "text-bad" : "text-ink";
  return (
    <div className="rounded-2xl bg-paper p-5 ring-1 ring-line">
      <dt className="text-base text-ink-soft">{label}</dt>
      <dd className={`mt-1 font-display text-3xl font-bold ${color}`}>{formatUsd(cents)}</dd>
    </div>
  );
}
