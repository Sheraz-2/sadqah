"use client";

import Link from "next/link";
import { get } from "@/lib/api";
import { formatNumber, formatUsd, timeAgo } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { CampaignCard } from "@/components/campaign/CampaignCard";
import { Alert } from "@/components/ui/Alert";
import { Button, LinkButton } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { Star } from "@/components/ui/Star";
import type { CampaignCard as Card, GratitudeItem, PublicStats } from "@/types/api";

const STEPS = [
  ["Give", "Choose a person and an amount from $1. Give publicly, or anonymously with a private token. PayPal handles the payment."],
  ["It joins a verified batch", "Every recipient has passed identity, address and income checks, and a human reviewer approved them. Gifts are grouped into payout batches."],
  ["Follow it and hear back", "Watch your gift move from queued to delivered. Once it arrives, the recipient can send a thank-you and you can exchange anonymous, moderated messages."],
];

export default function HomePage() {
  const featured = useAsync((s) => get<{ items: Card[]; total: number }>("/public/campaigns?sort=almost_funded&limit=3", s), []);
  const stats = useAsync((s) => get<PublicStats>("/public/stats", s), []);
  const thanks = useAsync((s) => get<{ items: GratitudeItem[] }>("/public/gratitude?limit=6", s), []);
  const lead = featured.data?.items[0];

  return (
    <>
      {/* ------------------------------------------------------------ hero */}
      <section className="pattern-stars relative overflow-hidden bg-lapis-900 text-white">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 md:grid-cols-[1.1fr_1fr] md:py-24">
          <div>
            <p className="flex items-center gap-2 text-base font-semibold text-saffron-400">
              <Star className="size-5" /> Small grants. Verified people. Real follow-through.
            </p>
            <h1 className="mt-4 text-5xl font-bold sm:text-6xl">Five dollars can restock a stall.</h1>
            <p className="mt-6 max-w-xl text-xl text-lapis-100">
              SadQah sends small grants to verified people who live on less than $50 a month. Give publicly or anonymously, then follow exactly where your gift went.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <LinkButton href="/campaigns" variant="give" size="lg">
                Choose someone to help
              </LinkButton>
              <Link href="/about" className="inline-flex h-14 items-center rounded-full px-6 text-lg font-semibold text-white ring-1 ring-inset ring-white/40 hover:bg-white/10">
                What does SadQah mean?
              </Link>
            </div>
          </div>

          <div className="animate-settle">
            {featured.loading && !featured.data ? (
              <div className="rounded-2xl bg-white/10 p-6 text-white">
                <Spinner label="Finding someone to help" />
              </div>
            ) : lead ? (
              <div className="text-ink">
                <CampaignCard campaign={lead} />
              </div>
            ) : (
              <div className="rounded-2xl bg-white/10 p-8 text-center" aria-hidden>
                <span lang="ar" dir="rtl" className="font-arabic text-[8rem] leading-none text-saffron-400">
                  صدقة
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-white/10 bg-lapis-900/60">
          <dl className="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-4 py-6 sm:px-6 md:grid-cols-4">
            <Stat label="People supported" value={stats.data ? formatNumber(stats.data.recipients_supported) : null} />
            <Stat label="Countries reached" value={stats.data ? formatNumber(stats.data.countries_reached) : null} />
            <Stat label="Gifts given" value={stats.data ? formatNumber(stats.data.gifts_given) : null} />
            <Stat label="Given in total" value={stats.data ? formatUsd(stats.data.total_given_cents) : null} />
          </dl>
        </div>
      </section>

      {/* ------------------------------------------------------------ almost funded */}
      <section className="mx-auto max-w-6xl px-4 pt-20 sm:px-6" aria-labelledby="close-h">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="close-h" className="text-4xl font-bold">
            Close to their goal
          </h2>
          <Link href="/campaigns?sort=almost_funded" className="font-semibold text-lapis-700 underline">
            See all campaigns
          </Link>
        </div>
        <div className="mt-8">
          {featured.error && !featured.data ? (
            <Alert tone="bad" title="We could not load campaigns.">
              <Button variant="secondary" size="sm" className="mt-2" onClick={() => void featured.reload()}>
                Try again
              </Button>
            </Alert>
          ) : featured.loading && !featured.data ? (
            <Spinner label="Loading campaigns" />
          ) : featured.data && featured.data.items.length === 0 ? (
            <EmptyState title="No campaigns are open right now" action={<LinkButton href="/about" variant="secondary">Learn about SadQah</LinkButton>}>
              New people are verified every week. Please check back soon.
            </EmptyState>
          ) : (
            <ul className="grid gap-6 md:grid-cols-3">
              {featured.data?.items.map((c) => (
                <li key={c.slug}>
                  <CampaignCard campaign={c} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------------ how it works */}
      <section className="mx-auto max-w-6xl px-4 pt-24 sm:px-6" aria-labelledby="how-h">
        <h2 id="how-h" className="text-4xl font-bold">
          How a gift travels
        </h2>
        <ol className="mt-8 grid gap-6 md:grid-cols-3">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="rounded-2xl bg-paper p-6 ring-1 ring-line">
              <span className="font-display text-5xl font-bold text-saffron-400" aria-hidden>
                {i + 1}
              </span>
              <h3 className="mt-2 text-2xl font-semibold">{title}</h3>
              <p className="mt-2 text-ink-soft">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* ------------------------------------------------------------ gratitude wall */}
      <section className="mx-auto max-w-6xl px-4 pt-24 sm:px-6" aria-labelledby="thanks-h">
        <h2 id="thanks-h" className="text-4xl font-bold">
          Thank-yous from the people you helped
        </h2>
        <div className="mt-8">
          {thanks.loading && !thanks.data ? (
            <Spinner label="Loading thank-yous" />
          ) : thanks.data && thanks.data.items.length > 0 ? (
            <ul className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
              {thanks.data.items.map((g) => (
                <li key={g.id} className="flex flex-col rounded-2xl bg-lapis-50 p-6 ring-1 ring-lapis-100">
                  <p className="whitespace-pre-wrap break-words text-lg">&ldquo;{g.body}&rdquo;</p>
                  <p className="mt-auto pt-4 text-sm text-ink-soft">
                    <strong className="text-ink">{g.recipient_name}</strong> to {g.thanks_to} · {timeAgo(g.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-ink-soft">Thank-you notes will appear here as gifts are delivered and recipients reply.</p>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------------ about teaser */}
      <section className="mx-auto mt-24 max-w-6xl px-4 sm:px-6">
        <div className="pattern-stars flex flex-col items-start justify-between gap-6 rounded-3xl bg-lapis-900 p-8 text-white sm:p-12 md:flex-row md:items-center">
          <div>
            <h2 className="text-3xl font-bold sm:text-4xl">Not sure how much to give?</h2>
            <p className="mt-2 max-w-xl text-lapis-100">Many people give 1% to 5% of their yearly income. Try the giving calculator: your income never leaves your browser.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <LinkButton href="/give" variant="give">
              Plan my giving
            </LinkButton>
            <LinkButton href="/about" variant="secondary">
              About SadQah
            </LinkButton>
          </div>
        </div>
      </section>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-sm font-medium uppercase tracking-wide text-lapis-100/80">{label}</dt>
      <dd className="font-display text-3xl font-bold text-white">{value ?? <span className="opacity-40">…</span>}</dd>
    </div>
  );
}
