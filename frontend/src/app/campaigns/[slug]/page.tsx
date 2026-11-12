"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { get } from "@/lib/api";
import { formatDate, formatNumber, formatUsd, regionLabel, timeAgo } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { ReportCampaign } from "@/components/campaign/ReportCampaign";
import { CommentThread } from "@/components/campaign/CommentThread";
import { DonateModal } from "@/components/donate/DonateModal";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button, LinkButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Spinner } from "@/components/ui/Spinner";
import type { CampaignDetail } from "@/types/api";

export default function CampaignPage() {
  return (
    <Suspense fallback={<Spinner label="Loading campaign" />}>
      <CampaignView />
    </Suspense>
  );
}

function CampaignView() {
  const { slug } = useParams<{ slug: string }>();
  const amountParam = Number(useSearchParams().get("amount")) || null;
  const [giving, setGiving] = useState(false);
  const detail = useAsync((signal) => get<CampaignDetail>(`/public/campaigns/${encodeURIComponent(slug)}`, signal), [slug]);
  const c = detail.data;

  if (detail.loading && !c) return <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6"><Spinner label="Loading campaign" /></div>;
  if (!c) {
    const missing = detail.error && /find|not_found/i.test(detail.error);
    return (
      <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
        <EmptyState
          title={missing ? "This campaign is not available" : "We could not load this campaign"}
          action={<LinkButton href="/campaigns" variant="secondary">Browse campaigns</LinkButton>}
        >
          {missing ? "It may have closed, or the link may be mistyped." : detail.error ?? "Please try again in a moment."}
        </EmptyState>
      </div>
    );
  }

  const funded = c.status === "funded" || c.remaining_cents <= 0;
  return (
    <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
      <p className="text-base text-ink-soft">
        {c.recipient.name}
        {c.recipient.business_type ? ` · ${c.recipient.business_type}` : ""} · {regionLabel(c.recipient.region_country, c.recipient.region_admin1)}
      </p>
      <h1 className="mt-2 max-w-4xl text-4xl font-bold sm:text-5xl">{c.title}</h1>

      <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-12">
          {c.cover_url && <img src={c.cover_url} alt="" className="max-h-96 w-full rounded-2xl object-cover" />}
          <section aria-labelledby="story-h">
            <h2 id="story-h" className="text-3xl font-semibold">
              Their story
            </h2>
            <p className="mt-4 whitespace-pre-wrap break-words text-lg leading-relaxed">{c.story}</p>
          </section>

          <section aria-labelledby="updates-h">
            <h2 id="updates-h" className="text-3xl font-semibold">
              Updates
            </h2>
            {c.updates.length === 0 ? (
              <p className="mt-4 text-ink-soft">No updates yet. {c.recipient.name} will post here as the work begins.</p>
            ) : (
              <ol className="mt-5 space-y-5">
                {c.updates.map((u) => (
                  <li key={u.id} className="rounded-2xl bg-paper p-5 ring-1 ring-line">
                    <p className="text-sm text-ink-soft">{formatDate(u.created_at)}</p>
                    <p className="mt-1 whitespace-pre-wrap break-words">{u.body}</p>
                    {u.media_urls.length > 0 && (
                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        {u.media_urls.map((m) => (
                          <img key={m} src={m} alt={`Photo from ${c.recipient.name}'s update`} loading="lazy" className="rounded-xl" />
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </section>

          <CommentThread slug={c.slug} comments={c.comments} onPosted={() => void detail.reload()} />
        </div>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <Card className="space-y-4">
            <div>
              <p className="font-display text-4xl font-bold">{formatUsd(c.raised_cents)}</p>
              <p className="text-ink-soft">
                raised of {formatUsd(c.goal_cents)} · {formatNumber(c.donor_count)} {c.donor_count === 1 ? "gift" : "gifts"}
              </p>
            </div>
            <ProgressBar percent={c.percent_funded} label="Funding progress" />
            {funded ? (
              <Alert tone="ok" title="Fully funded">
                Thank you. This goal has been reached.
              </Alert>
            ) : (
              <Button variant="give" size="lg" className="w-full" onClick={() => setGiving(true)}>
                Give to {c.recipient.name}
              </Button>
            )}
            <p className="text-sm text-ink-soft">{funded ? "" : `${formatUsd(c.remaining_cents)} still needed.`} Gifts are verified, batched and paid out through PayPal. <Link href="/trust" className="underline underline-offset-2">Fees, timing and refunds</Link>.</p>
            <ReportCampaign slug={c.slug} />
          </Card>

          <Card className="mt-6">
            <h2 className="text-xl font-semibold">Recent gifts</h2>
            {c.recent_gifts.length === 0 ? (
              <p className="mt-2 text-ink-soft">Be the first to give.</p>
            ) : (
              <ul className="mt-3 divide-y divide-line">
                {c.recent_gifts.map((g, i) => (
                  <li key={i} className="flex items-baseline justify-between gap-3 py-2">
                    <span>
                      {g.label}
                      {g.is_anonymous && <Badge className="ml-2">anonymous</Badge>}
                    </span>
                    <span className="text-right">
                      <strong>{formatUsd(g.amount_cents)}</strong>
                      <span className="block text-sm text-ink-soft">{timeAgo(g.given_at)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </aside>
      </div>

      <DonateModal
        open={giving}
        onClose={() => setGiving(false)}
        campaign={{ slug: c.slug, title: c.title, recipientName: c.recipient.name, remainingCents: c.remaining_cents }}
        initialAmountCents={amountParam}
        onGiven={() => void detail.reload()}
      />
    </div>
  );
}

