"use client";

import Link from "next/link";
import { get } from "@/lib/api";
import { useAsync } from "@/hooks/useAsync";
import { Alert } from "@/components/ui/Alert";
import { Spinner } from "@/components/ui/Spinner";
import type { AdminOverview } from "@/types/admin";

export default function AdminHome() {
  const o = useAsync((s) => get<AdminOverview>("/admin/overview", s), []);
  if (o.loading && !o.data) return <Spinner label="Loading" />;
  if (!o.data) return <Alert tone="bad">{o.error ?? "Could not load the overview."}</Alert>;
  const d = o.data;
  const cards: { href: string; label: string; count: number | null; hot: boolean; hint: string }[] = [
    { href: "/admin/kyc", label: "Applications to review", count: d.kyc_waiting, hot: d.kyc_waiting > 0, hint: "Assessed and waiting for a human decision" },
    { href: "/admin/payouts", label: "Payouts needing attention", count: d.payouts_needing_attention, hot: d.payouts_needing_attention > 0, hint: "Failed, blocked or returned" },
    { href: "/admin/payouts", label: "Open payout batches", count: d.batches_open, hot: false, hint: "Created, retrying or in flight" },
    { href: "/admin/moderation", label: "Messages to moderate", count: d.messages_pending, hot: d.messages_pending > 0, hint: "Anonymous donor and recipient messages" },
    { href: "/admin/moderation", label: "Thank-yous to moderate", count: d.gratitude_pending, hot: d.gratitude_pending > 0, hint: "Recipient gratitude notes" },
  ];
  return (
    <div className="space-y-8">
      <h1 className="text-4xl font-bold">Today</h1>
      <Alert tone={d.reconciliation_ok ? "ok" : "bad"} title={d.reconciliation_ok ? "Money reconciles" : "Reconciliation found a mismatch"}>
        {d.reconciliation_ok ? "Every campaign total matches its donation and payout records." : <>Some campaign totals do not match. <Link href="/admin/reconciliation" className="font-semibold underline">Investigate now</Link>.</>}
      </Alert>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((c) => (
          <li key={c.label}>
            <Link href={c.href} className={`block rounded-2xl p-5 ring-1 transition-shadow hover:shadow-[var(--shadow-lift)] ${c.hot ? "bg-saffron-100 ring-saffron-400/60" : "bg-paper ring-line"}`}>
              <span className="font-display text-4xl font-bold">{c.count}</span>
              <span className="mt-1 block font-semibold">{c.label}</span>
              <span className="block text-sm text-ink-soft">{c.hint}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
