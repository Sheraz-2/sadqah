"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { get } from "@/lib/api";
import { formatNumber, formatUsd } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";

type Stats = {
  gifts_received: number;
  gifts_delivered: number;
  raised_cents: number;
  delivered_cents: number;
  awaiting_payout_cents: number;
  platform_fees_cents: number;
  refunds: number;
  median_payout_seconds: number | null;
};

function duration(sec: number): string {
  if (sec < 90) return `${sec} seconds`;
  if (sec < 5400) return `${Math.round(sec / 60)} minutes`;
  if (sec < 172800) return `${Math.round(sec / 3600)} hours`;
  return `${Math.round(sec / 86400)} days`;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-4">
      <p className="text-sm text-ink-soft">{label}</p>
      <p className="font-display text-3xl font-bold text-lapis-900">{value}</p>
      {hint && <p className="mt-1 text-sm text-ink-soft">{hint}</p>}
    </Card>
  );
}

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-2 scroll-mt-24">
      <h2 id={id} className="font-display text-2xl font-semibold text-lapis-900">{title}</h2>
      <div className="space-y-2 text-lg leading-relaxed text-ink">{children}</div>
    </section>
  );
}

export default function TrustPage() {
  const s = useAsync((sig) => get<Stats>("/public/trust-stats", sig), []);
  const d = s.data;
  return (
    <div className="mx-auto max-w-3xl space-y-10 px-4 py-12 sm:px-6">
      <header>
        <h1 className="font-display text-4xl font-bold text-lapis-900 sm:text-5xl">Trust &amp; transparency</h1>
        <p className="mt-3 text-xl text-ink-soft">What happens to a gift, what it costs, and what to do if something looks wrong. Numbers on this page come straight from our records.</p>
      </header>

      <section aria-labelledby="numbers" className="space-y-3">
        <h2 id="numbers" className="font-display text-2xl font-semibold text-lapis-900">The numbers, live</h2>
        {s.loading && !d ? <Spinner label="Loading the numbers" /> : !d ? (
          <Alert tone="warn">We could not load the numbers just now. Please try again in a moment.</Alert>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Stat label="Gifts received" value={formatNumber(d.gifts_received)} hint={`${formatUsd(d.raised_cents)} in total`} />
              <Stat label="Gifts delivered to recipients" value={formatNumber(d.gifts_delivered)} hint={`${formatUsd(d.delivered_cents)} paid out`} />
              <Stat label="Waiting to be paid out" value={formatUsd(d.awaiting_payout_cents)} hint="Paid out in batches, see below" />
              <Stat label="Typical time to payout" value={d.median_payout_seconds == null ? "Not enough data yet" : duration(d.median_payout_seconds)} hint="Median, from gift to payout" />
              <Stat label="Platform fees taken" value={formatUsd(d.platform_fees_cents)} />
              <Stat label="Refunds" value={formatNumber(d.refunds)} />
            </div>
            <p className="text-sm text-ink-soft">No names or personal details are included, only counts and totals.</p>
          </>
        )}
      </section>

      <Block id="journey" title="What happens to a gift">
        <ol className="list-decimal space-y-1 pl-6">
          <li>You give through PayPal. SadQah never sees your card number.</li>
          <li>When PayPal confirms the payment, the gift is recorded in an append-only ledger. Entries are never edited or deleted.</li>
          <li>Gifts for a recipient are queued and paid out in batches to the PayPal email or phone they registered.</li>
          <li>Each gift shows its stage on <Link href="/track" className="font-semibold text-lapis-700 underline underline-offset-2">Track a gift</Link>: received, queued, paid out, or on hold.</li>
        </ol>
      </Block>

      <Block id="verified" title="What &ldquo;verified&rdquo; means">
        <p>Before a campaign can take gifts, the person completes an identity check: documents are read by software and then looked at by a SadQah reviewer. A person makes the final decision, never software alone.</p>
        <p>A campaign shows when it is verified. Recipients can also send a list of what they need with a photo as proof. We compare prices with typical local prices and a reviewer decides. The price comparison is an AI estimate, so it is advice for the reviewer, not a promise about any price.</p>
        <p>Verification lowers the risk. It cannot remove it. If a story feels wrong to you, tell us.</p>
      </Block>

      <Block id="fees" title="Fees and timing">
        <p>SadQah does not take a platform fee on gifts in this version (the figure above is read from the ledger). PayPal may charge processing fees, and who bears them is set out when you give and in PayPal&rsquo;s own terms.</p>
        <p>Payouts are batched to keep costs and paperwork low: a batch is sent once enough gifts are ready, or once the oldest gift has waited about 15 minutes. After that, how long the money takes to reach the recipient depends on PayPal and on their country. Gifts can be held for review, and held gifts are shown as held.</p>
      </Block>

      <Block id="refunds" title="Refunds and problems with a gift">
        <p>If PayPal refunds or reverses a payment, SadQah records that automatically and the gift is shown as returned. If you gave by mistake or think you were tricked, <Link href="/contact" className="font-semibold text-lapis-700 underline underline-offset-2">email SadQah support</Link> as soon as you can with your Donation Token or the email you gave with, and also raise it with PayPal. A person looks at every request. We cannot promise a refund, because gifts that have already been paid out cannot always be recovered.</p>
      </Block>

      <Block id="report" title="Report a campaign">
        <p>Every campaign page has a <strong>Report this campaign</strong> button. You can report a story that is fake or misleading, someone who does not seem to be in need, impersonation, or inappropriate content. You can report without an account. Reports go to a SadQah reviewer, and many reports about one campaign move it up the queue. Reports are not shown to the recipient.</p>
      </Block>

      <Block id="privacy" title="Privacy and your data">
        <p>You can give anonymously. An anonymous gift is never ranked and is only shown by the day. You get a Donation Token to follow it. You can download your data or delete your account in <Link href="/settings" className="font-semibold text-lapis-700 underline underline-offset-2">Settings</Link>. Deleting removes your personal details. Records of money that moved must be kept, but are made anonymous.</p>
      </Block>

      <Block id="calculator" title="About the giving calculator">
        <p>The calculator suggests 1% to 5% of your income as a starting point. That range is a voluntary suggestion made by SadQah. It is not a religious ruling and not a tax or legal figure. Give what you are able to, or any amount you choose.</p>
      </Block>

      <Block id="ai" title="About the AI assistant">
        <p>The assistant answers questions and helps recipients price their needs. It can make mistakes. It cannot see your account or payments, and it cannot approve, refuse, refund or pay anything. Please do not type passwords, card numbers or ID numbers into it.</p>
      </Block>
    </div>
  );
}
