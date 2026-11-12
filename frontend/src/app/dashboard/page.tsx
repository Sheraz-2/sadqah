"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type { ColDef } from "ag-grid-community";
import { ApiError, del, get, patch, put } from "@/lib/api";
import { formatDate, formatUsd, timeAgo } from "@/lib/format";
import { MAX_PERCENT, MIN_PERCENT, paymentCents, parseDollars, pledgeAmountProblem, yearlyGiftCents, type Frequency } from "@/lib/giving";
import { homeFor, useAuth } from "@/hooks/useAuth";
import { useAsync } from "@/hooks/useAsync";
import { DataGrid } from "@/components/grids/DataGrid";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import type { DonorThread, MyDonation, Me, Pledge } from "@/types/api";

type Gratitude = { id: string; donation_id: string; recipient_name: string; body: string; created_at: string };

export default function DashboardPage() {
  const router = useRouter();
  const { me, loading } = useAuth();

  useEffect(() => {
    if (!loading && !me) router.replace("/login?next=%2Fdashboard");
    else if (me && me.role !== "donor") router.replace(homeFor(me.role));
  }, [me, loading, router]);

  if (loading || !me || me.role !== "donor") return <div className="mx-auto max-w-6xl px-4 py-14"><Spinner label="Loading your giving page" /></div>;
  return <Dashboard me={me} />;
}

function Dashboard({ me }: { me: Me }) {
  const gifts = useAsync((s) => get<{ items: MyDonation[] }>("/me/donations", s), []);
  const thanks = useAsync((s) => get<{ items: Gratitude[] }>("/me/gratitude", s), []);
  const threads = useAsync((s) => get<{ items: DonorThread[] }>("/me/threads", s), []);
  const unread = (threads.data?.items ?? []).reduce((n, t) => n + t.unread_count, 0);

  const columns = useMemo<ColDef<MyDonation>[]>(
    () => [
      { field: "campaign_title", headerName: "Campaign", flex: 3 },
      { field: "amount_cents", headerName: "Amount", valueFormatter: (p) => formatUsd(Number(p.value)), filter: "agNumberColumnFilter" },
      { field: "status", headerName: "Status" },
      { field: "created_at", headerName: "Given", valueFormatter: (p) => formatDate(String(p.value)) },
      { field: "paid_out_at", headerName: "Delivered", valueFormatter: (p) => (p.value ? formatDate(String(p.value)) : "Not yet") },
    ],
    [],
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
      <h1 className="text-5xl font-bold">Hello{me.display_name ? `, ${me.display_name}` : ""}</h1>
      <p className="mt-3 max-w-2xl text-lg text-ink-soft">Your public gifts, your giving plan and any thank-yous. Gifts you gave anonymously are deliberately not linked to this account: follow them with your token on the <Link href="/track" className="font-semibold underline">Track page</Link>.</p>

      <p className="mt-4">
        <Link href="/dashboard/messages" className="inline-flex items-center gap-2 font-semibold underline">
          Messages{unread > 0 && <Badge tone="info">{unread} new</Badge>}
        </Link>
      </p>

      <section className="mt-10" aria-labelledby="gifts-h">
        <h2 id="gifts-h" className="text-3xl font-semibold">My gifts</h2>
        <div className="mt-4">
          {gifts.error && !gifts.data ? (
            <Alert tone="bad">We could not load your gifts. Please refresh.</Alert>
          ) : (
            <DataGrid<MyDonation> label="My gifts" rows={gifts.data?.items ?? null} loading={gifts.loading} columns={columns} rowId={(r) => r.id} paginate={10} emptyText="No public gifts yet." />
          )}
        </div>
      </section>

      <div className="mt-12 grid gap-8 lg:grid-cols-2">
        <PledgeCard />
        <div className="space-y-8">
          <LeaderboardCard me={me} />
          <section aria-labelledby="thanks-h">
            <h2 id="thanks-h" className="text-3xl font-semibold">Thank-yous for you</h2>
            {thanks.data && thanks.data.items.length > 0 ? (
              <ul className="mt-4 space-y-3">
                {thanks.data.items.map((g) => (
                  <li key={g.id} className="rounded-2xl bg-saffron-100 p-5">
                    <p className="whitespace-pre-wrap break-words">{g.body}</p>
                    <p className="mt-2 text-sm text-ink-soft">{g.recipient_name} · {timeAgo(g.created_at)}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-ink-soft">{thanks.loading ? "Loading…" : "When a recipient thanks you, it will appear here."}</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function LeaderboardCard({ me }: { me: Me }) {
  const { setMe } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      setMe(await patch<Me>("/me", { show_on_leaderboard: !me.show_on_leaderboard }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <h2 className="text-2xl font-semibold">Leaderboard</h2>
      <p className="mt-2 text-ink-soft">{me.show_on_leaderboard ? "Your name appears on the public leaderboard for your public gifts." : "You are hidden from the public leaderboard."}</p>
      {error && <Alert tone="bad" className="mt-3">{error}</Alert>}
      <Button className="mt-4" variant="secondary" loading={busy} onClick={() => void toggle()}>
        {me.show_on_leaderboard ? "Hide me from the leaderboard" : "Show me on the leaderboard"}
      </Button>
    </Card>
  );
}

function PledgeCard() {
  const pledge = useAsync((s) => get<Pledge | null>("/me/pledge", s), []);
  const [kind, setKind] = useState<Pledge["kind"]>("percent_of_income");
  const [percent, setPercent] = useState(2);
  const [income, setIncome] = useState(""); // stays in this browser: only the resulting amount is sent
  const [fixed, setFixed] = useState("");
  const [frequency, setFrequency] = useState<Frequency>("monthly");
  const [anon, setAnon] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  useEffect(() => {
    const p = pledge.data;
    if (!p) return;
    setKind(p.kind);
    if (p.percent) setPercent(p.percent);
    if (p.kind === "fixed_amount") setFixed(String(p.amount_cents / 100));
    setFrequency(p.frequency);
    setAnon(p.default_anonymous);
  }, [pledge.data]);

  const amount = kind === "percent_of_income" ? paymentCents(yearlyGiftCents(parseDollars(income), percent), frequency) : Math.round(parseDollars(fixed) * 100);
  const problem = amount > 0 ? pledgeAmountProblem(amount) : kind === "percent_of_income" ? "Enter your yearly income to see the amount." : "Enter an amount.";

  async function save(e: FormEvent) {
    e.preventDefault();
    if (problem) return;
    setBusy(true);
    setMsg(null);
    try {
      await put<Pledge>("/me/pledge", { kind, percent: kind === "percent_of_income" ? percent : undefined, amount_cents: amount, frequency, default_anonymous: anon });
      setMsg({ tone: "ok", text: "Your giving plan is saved. SadQah never stores your income." });
      void pledge.reload();
    } catch (err) {
      setMsg({ tone: "bad", text: err instanceof ApiError ? err.message : "Could not save your plan." });
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await del("/me/pledge");
      setMsg({ tone: "ok", text: "Your giving plan was removed." });
      void pledge.reload();
    } catch (err) {
      setMsg({ tone: "bad", text: err instanceof ApiError ? err.message : "Could not remove your plan." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h2 className="text-2xl font-semibold">My giving plan</h2>
      <p className="mt-1 text-ink-soft">A gentle reminder of what you intend to give. It does not charge you: you still choose each gift.</p>
      <form onSubmit={save} className="mt-5 space-y-4">
        <Select label="Plan type" value={kind} onChange={(e) => setKind(e.target.value as Pledge["kind"])}>
          <option value="percent_of_income">A share of my income</option>
          <option value="fixed_amount">A fixed amount</option>
        </Select>
        {kind === "percent_of_income" ? (
          <>
            <Select label="Share of yearly income" value={String(percent)} onChange={(e) => setPercent(Number(e.target.value))}>
              {Array.from({ length: (MAX_PERCENT - MIN_PERCENT) * 2 + 1 }, (_, i) => MIN_PERCENT + i / 2).map((p) => (
                <option key={p} value={p}>{p}%</option>
              ))}
            </Select>
            <Input label="Yearly income (USD)" inputMode="decimal" value={income} onChange={(e) => setIncome(e.target.value)} hint="Used only in your browser to work out the amount. It is never sent or saved." />
          </>
        ) : (
          <Input label="Amount per payment (USD)" inputMode="decimal" value={fixed} onChange={(e) => setFixed(e.target.value)} />
        )}
        <Select label="How often" value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}>
          <option value="one_time">Once</option>
          <option value="monthly">Monthly</option>
          <option value="yearly">Yearly</option>
        </Select>
        <label className="flex items-center gap-3">
          <input type="checkbox" checked={anon} onChange={(e) => setAnon(e.target.checked)} className="size-5 accent-[#1b4580]" />
          <span>Give anonymously by default</span>
        </label>
        <p className="rounded-xl bg-lapis-50 p-3" aria-live="polite">
          {problem ? <span className="text-ink-soft">{problem}</span> : <>That is <strong>{formatUsd(amount)}</strong> {frequency === "monthly" ? "each month" : frequency === "yearly" ? "each year" : "once"}.</>}
        </p>
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <div className="flex flex-wrap gap-3">
          <Button type="submit" loading={busy} disabled={!!problem}>Save my plan</Button>
          {pledge.data && <Button type="button" variant="ghost" disabled={busy} onClick={() => void remove()}>Remove plan</Button>}
          <Link href="/campaigns" className="inline-flex h-11 items-center px-3 font-semibold text-lapis-700 underline">Choose someone to give to</Link>
        </div>
      </form>
    </Card>
  );
}
