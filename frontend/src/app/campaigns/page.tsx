"use client";

import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { get } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { useAsync } from "@/hooks/useAsync";
import { CampaignCard } from "@/components/campaign/CampaignCard";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input, Select } from "@/components/ui/Field";
import { CountrySelect } from "@/components/ui/CountrySelect";
import { Spinner } from "@/components/ui/Spinner";
import type { CampaignCard as Card } from "@/types/api";

const PAGE_SIZE = 12;
const SORTS = [
  ["newest", "Newest"],
  ["almost_funded", "Closest to goal"],
  ["most_supported", "Most supported"],
] as const;

export default function CampaignsPage() {
  return (
    <Suspense fallback={<Spinner label="Loading campaigns" />}>
      <CampaignsView />
    </Suspense>
  );
}

function CampaignsView() {
  const router = useRouter();
  const params = useSearchParams();
  const q = params.get("q") ?? "";
  const country = params.get("country") ?? "";
  const sort = (params.get("sort") ?? "newest") as (typeof SORTS)[number][0];
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const amount = Number(params.get("amount")) || null; // cents, carried over from the giving calculator
  const [text, setText] = useState(q);

  const list = useAsync(
    (signal) => {
      const qs = new URLSearchParams({ sort, limit: String(PAGE_SIZE), offset: String((page - 1) * PAGE_SIZE) });
      if (q) qs.set("q", q);
      if (country) qs.set("country", country);
      return get<{ items: Card[]; total: number }>(`/public/campaigns?${qs}`, signal);
    },
    [q, country, sort, page],
  );

  function go(next: Record<string, string | null>) {
    const qs = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(next)) {
      if (v) qs.set(k, v);
      else qs.delete(k);
    }
    if (!("page" in next)) qs.delete("page");
    router.replace(`/campaigns${qs.toString() ? `?${qs}` : ""}`);
  }

  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
      <h1 className="text-5xl font-bold">Choose someone to help</h1>
      <p className="mt-4 max-w-2xl text-lg text-ink-soft">Every person here has been verified by a human reviewer. We show only their first name and region, never anything finer.</p>

      {amount ? (
        <Alert tone="info" className="mt-6">
          You planned to give <strong>{formatUsd(amount)}</strong>. Pick a campaign and we will fill that amount in for you.
        </Alert>
      ) : null}

      <form
        role="search"
        className="mt-8 grid gap-4 rounded-2xl bg-paper p-5 ring-1 ring-line md:grid-cols-[2fr_1fr_1fr_auto] md:items-end"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          go({ q: text.trim() || null });
        }}
      >
        <Input label="Search" placeholder="Name, trade or story" value={text} onChange={(e) => setText(e.target.value)} />
        <CountrySelect label="Country" value={country} onChange={(c) => go({ country: c || null })} anyLabel="All countries" placeholder="Type a country…" />
        <Select label="Sort by" value={sort} onChange={(e) => go({ sort: e.target.value })}>
          {SORTS.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </Select>
        <Button type="submit">Search</Button>
      </form>

      <div className="mt-8" aria-live="polite">
        {list.error && !list.data ? (
          <Alert tone="bad" title="We could not load campaigns.">
            <Button variant="secondary" size="sm" className="mt-2" onClick={() => void list.reload()}>
              Try again
            </Button>
          </Alert>
        ) : list.loading && !list.data ? (
          <Spinner label="Loading campaigns" />
        ) : list.data && list.data.items.length === 0 ? (
          <EmptyState
            title="No campaigns match"
            action={
              <Button variant="secondary" onClick={() => { setText(""); router.replace("/campaigns"); }}>
                Clear filters
              </Button>
            }
          >
            Try a different country or search term.
          </EmptyState>
        ) : (
          <>
            <p className="text-ink-soft">
              {total} {total === 1 ? "campaign" : "campaigns"}
            </p>
            <ul className="mt-4 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {list.data?.items.map((c) => (
                <li key={c.slug}>
                  <CampaignCard campaign={c} amount={amount} />
                </li>
              ))}
            </ul>
            {pages > 1 && (
              <nav aria-label="Pages" className="mt-8 flex items-center justify-center gap-4">
                <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => go({ page: String(page - 1) })}>
                  Previous
                </Button>
                <span className="text-ink-soft">
                  Page {page} of {pages}
                </span>
                <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => go({ page: String(page + 1) })}>
                  Next
                </Button>
              </nav>
            )}
          </>
        )}
      </div>
    </div>
  );
}
