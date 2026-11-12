"use client";

import { useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { ApiError, get, post, upload } from "@/lib/api";
import { currencyFor } from "@/lib/currencies";
import { formatDate, formatUsd } from "@/lib/format";
import { usePrefs } from "@/lib/prefs";
import { useDictation } from "@/lib/speech";
import { useAsync } from "@/hooks/useAsync";
import { RecipientShell } from "@/components/recipient/RecipientNav";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import type { NeedsRequest, PriceCheck, PriceStatus } from "@/types/assistant";
import type { RecipientMe } from "@/types/api";

type Row = { key: number; name: string; qty: string; price: string };

const STATUS_TEXT: Record<PriceStatus, { t: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  ok: { t: "In the usual range", tone: "ok" },
  high: { t: "Above the usual range", tone: "warn" },
  very_high: { t: "Far above the usual range", tone: "bad" },
  low: { t: "Lower than usual", tone: "neutral" },
  unknown: { t: "No reliable estimate", tone: "neutral" },
};

const REQUEST_TEXT: Record<NeedsRequest["status"], { t: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  submitted: { t: "With a reviewer", tone: "neutral" },
  approved: { t: "Approved", tone: "ok" },
  declined: { t: "Not approved", tone: "bad" },
  more_info: { t: "More information needed", tone: "warn" },
};

const money = (n: number, cur: string) => {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: cur, maximumFractionDigits: n < 100 ? 2 : 0 }).format(n);
  } catch {
    return `${cur} ${n.toLocaleString()}`;
  }
};

export default function NeedsPage() {
  return (
    <RecipientShell title="Needs & price check" intro="List what you need. We compare each price with typical local prices, and a person reviews it with your proof.">
      {({ rme }) => <Needs rme={rme} />}
    </RecipientShell>
  );
}

function Needs({ rme }: { rme: RecipientMe }) {
  const mine = useAsync((s) => get<{ items: NeedsRequest[] }>("/assistant/needs", s), []);
  if (!rme.profile) {
    return (
      <Alert tone="info" title="Create your profile first">
        We use your country and business type to compare prices. <Link href="/recipient/profile" className="font-semibold underline underline-offset-2">Go to Profile &amp; payout</Link>.
      </Alert>
    );
  }
  return (
    <div className="space-y-10">
      <Builder rme={rme} onSubmitted={() => void mine.reload()} />
      <section aria-labelledby="past">
        <h2 id="past" className="font-display text-2xl font-semibold">Your submitted lists</h2>
        {mine.loading && !mine.data ? <Spinner label="Loading" /> : !mine.data?.items.length ? (
          <p className="mt-2 text-ink-soft">Nothing yet.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {mine.data.items.map((r) => {
              const s = REQUEST_TEXT[r.status] ?? REQUEST_TEXT.submitted;
              return (
                <li key={r.id}>
                  <Card className="space-y-2 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium">{formatDate(r.created_at)} · {r.items.length} item{r.items.length === 1 ? "" : "s"}</p>
                      <Badge tone={s.tone}>{s.t}</Badge>
                    </div>
                    <p className="text-ink-soft">{r.items.map((i) => i.name).filter(Boolean).join(", ")}</p>
                    {r.requested_total_cents > 0 && <p className="text-sm text-ink-soft">Asked: about {formatUsd(r.requested_total_cents)}</p>}
                    {r.reviewer_note && <Alert tone={r.status === "approved" ? "ok" : "info"} title="Note from the reviewer">{r.reviewer_note}</Alert>}
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function ItemRow({ row, index, canRemove, onChange, onRemove, currency }: { row: Row; index: number; canRemove: boolean; onChange: (r: Row) => void; onRemove: () => void; currency: string }) {
  const prefs = usePrefs();
  const dict = useDictation(prefs.voiceLang, (t) => onChange({ ...row, name: t.slice(0, 120) }));
  return (
    <li className="grid gap-3 rounded-xl bg-white p-3 ring-1 ring-line sm:grid-cols-[1fr_6rem_9rem_auto] sm:items-end">
      <div className="space-y-1.5">
        <label htmlFor={`n-${row.key}`} className="block font-semibold">What do you need? <span className="sr-only">(item {index + 1})</span></label>
        <div className="flex gap-2">
          <input id={`n-${row.key}`} value={row.name} maxLength={120} dir="auto" placeholder={dict.listening ? "Listening…" : "e.g. flour, 50 kg bag"} onChange={(e) => onChange({ ...row, name: e.target.value })}
            className="w-full rounded-xl border-0 bg-white px-4 py-3 text-base ring-1 ring-inset ring-line focus:ring-2 focus:ring-lapis-500" />
          {dict.supported && (
            <button type="button" onClick={() => (dict.listening ? dict.stop() : dict.start())} aria-pressed={dict.listening} aria-label={`Speak item ${index + 1}`}
              className={`grid size-12 shrink-0 place-items-center rounded-xl ring-1 ring-line ${dict.listening ? "animate-pulse bg-pomegranate-500 text-white" : "bg-white text-lapis-900 hover:bg-lapis-50"}`}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
            </button>
          )}
        </div>
        {dict.error && <p role="alert" className="text-sm font-medium text-bad">{dict.error}</p>}
      </div>
      <Input label="How many" type="number" inputMode="decimal" min="0" step="any" value={row.qty} onChange={(e) => onChange({ ...row, qty: e.target.value })} />
      <Input label={`Price each (${currency})`} type="number" inputMode="decimal" min="0" step="any" value={row.price} onChange={(e) => onChange({ ...row, price: e.target.value })} />
      <Button type="button" variant="ghost" size="sm" disabled={!canRemove} onClick={onRemove} aria-label={`Remove item ${index + 1}`}>Remove</Button>
    </li>
  );
}

function Builder({ rme, onSubmitted }: { rme: RecipientMe; onSubmitted: () => void }) {
  const country = rme.profile!.region_country;
  const [currency, setCurrency] = useState(currencyFor(country));
  const seq = useRef(1);
  const [rows, setRows] = useState<Row[]>([{ key: 0, name: "", qty: "1", price: "" }]);
  const [why, setWhy] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [check, setCheck] = useState<PriceCheck | null>(null);
  const [busy, setBusy] = useState<"check" | "send" | null>(null);
  const [err, setErr] = useState<{ message: string; fields: Record<string, string> } | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const valid = rows.every((r) => r.name.trim().length >= 2 && Number(r.qty) > 0 && r.price !== "" && Number(r.price) >= 0) && /^[A-Za-z]{3}$/.test(currency);
  const body = () => ({
    currency: currency.toUpperCase(),
    explanation: why.trim(),
    items: rows.map((r) => ({ name: r.name.trim(), quantity: Number(r.qty), asked_price: Number(r.price) })),
  });
  const fail = (e: unknown) => setErr(e instanceof ApiError ? { message: e.message, fields: e.fields ?? {} } : { message: "Something went wrong. Please try again.", fields: {} });
  const edit = (next: Row[]) => { setRows(next); setCheck(null); setDone(null); };

  async function runCheck() {
    setErr(null); setBusy("check");
    try { setCheck(await post<PriceCheck>("/assistant/price-check", body())); } catch (e) { fail(e); } finally { setBusy(null); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return setErr({ message: "Please attach a photo or PDF that shows you need these things.", fields: { proof: "Proof is required." } });
    setErr(null); setBusy("send");
    try {
      const form = new FormData();
      form.append("payload", JSON.stringify(body()));
      form.append("proof", file);
      const res = await upload<{ message: string }>("/assistant/needs", form);
      setDone(res.message);
      setRows([{ key: seq.current++, name: "", qty: "1", price: "" }]); setWhy(""); setFile(null); setCheck(null);
      onSubmitted();
    } catch (ex) { fail(ex); } finally { setBusy(null); }
  }

  return (
    <form onSubmit={submit} className="space-y-6" aria-label="Needs list">
      <Alert tone="info" title="How this works">
        Type or speak each thing you need and the price you were quoted. We compare it with typical prices in {country}. These are AI estimates, not quotes.
        Then attach proof (a photo of your shop, a supplier quote, a damaged tool). A person at SadQah reviews every list and decides.
      </Alert>

      <Input label="Currency" hint="Three letters, like PKR, KES or USD. We guessed it from your country." value={currency} maxLength={3} onChange={(e) => { setCurrency(e.target.value.toUpperCase()); setCheck(null); }} className="max-w-48" />

      <ul className="space-y-3">
        {rows.map((r, i) => (
          <ItemRow key={r.key} row={r} index={i} currency={currency} canRemove={rows.length > 1}
            onChange={(n) => edit(rows.map((x) => (x.key === r.key ? n : x)))} onRemove={() => edit(rows.filter((x) => x.key !== r.key))} />
        ))}
      </ul>
      {rows.length < 20 && <Button type="button" variant="secondary" size="sm" onClick={() => edit([...rows, { key: seq.current++, name: "", qty: "1", price: "" }])}>Add another item</Button>}

      <Textarea label="Why do you need these?" hint="Say how they help your business. Any language is fine." value={why} maxLength={2000} rows={4} dir="auto" onChange={(e) => setWhy(e.target.value)} />

      <div className="space-y-2">
        <Button type="button" onClick={() => void runCheck()} loading={busy === "check"} disabled={!valid || busy !== null}>Check prices</Button>
        {!valid && <p className="text-sm text-ink-soft">Fill in a name, a number and a price for every item to check prices.</p>}
      </div>

      {check && <Results check={check} />}

      <Card className="space-y-3 p-5">
        <h2 className="font-display text-xl font-semibold">Proof</h2>
        <p className="text-ink-soft">A clear photo or PDF (up to 10 MB). It is stored encrypted and only a SadQah reviewer can open it. Do not send ID documents here.</p>
        <label htmlFor="proof" className="block font-semibold">Photo or PDF</label>
        <input id="proof" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-base file:mr-3 file:rounded-full file:border-0 file:bg-lapis-900 file:px-4 file:py-2 file:font-semibold file:text-white" />
        {err?.fields.proof && <p role="alert" className="text-sm font-medium text-bad">{err.fields.proof}</p>}
      </Card>

      {err && <Alert tone="bad">{err.message}</Alert>}
      {done && <Alert tone="ok" title="Sent">{done}</Alert>}
      <Button type="submit" size="lg" loading={busy === "send"} disabled={!valid || !file || busy !== null}>Send for review</Button>
    </form>
  );
}

function Results({ check }: { check: PriceCheck }) {
  const s = check.summary;
  const cur = check.currency;
  return (
    <section aria-label="Price check results" className="space-y-4">
      <h2 className="font-display text-2xl font-semibold">Price check</h2>
      {!check.ai_available && <Alert tone="warn" title="Price estimates are not available right now">You can still send your list. A reviewer will check the prices by hand.</Alert>}
      <ul className="space-y-3">
        {check.items.map((i) => {
          const st = STATUS_TEXT[i.status] ?? STATUS_TEXT.unknown;
          return (
            <li key={i.index}>
              <Card className="space-y-1.5 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold" dir="auto">{i.name} × {i.quantity}</p>
                  <Badge tone={st.tone}>{st.t}</Badge>
                </div>
                <p>You asked: <strong>{money(i.asked_unit_price, cur)}</strong> each ({money(i.asked_total, cur)} in all)</p>
                {i.low != null && i.high != null && <p className="text-ink-soft">Typical local price{i.unit ? ` per ${i.unit}` : ""}: {money(i.low, cur)} to {money(i.high, cur)}</p>}
                {(i.status === "high" || i.status === "very_high") && i.recommended_unit_price != null && (
                  <p className="font-medium text-lapis-900">A fair amount to ask: about {money(i.recommended_unit_price, cur)} each</p>
                )}
                {i.note && <p className="text-sm text-ink-soft" dir="auto">{i.note}</p>}
              </Card>
            </li>
          );
        })}
      </ul>
      <Card className="space-y-1 bg-lapis-50 p-4">
        <p>Total you asked: <strong>{money(s.asked_total_local, cur)}</strong>{s.asked_total_usd_cents != null && <> (about {formatUsd(s.asked_total_usd_cents)})</>}</p>
        {s.typical_total_local != null && <p>Typical total: {money(s.typical_total_local, cur)}</p>}
        <p>Suggested total: <strong>{money(s.suggested_total_local, cur)}</strong>{s.suggested_goal_usd_cents != null && <> · suggested campaign goal about <strong>{formatUsd(s.suggested_goal_usd_cents)}</strong></>}</p>
        {s.flags.includes("exceeds_approved_allocation") && <p className="font-medium text-bad">This is more than your approved limit. A reviewer will look at it closely.</p>}
      </Card>
      <p className="text-sm text-ink-soft">{check.disclaimer}</p>
    </section>
  );
}
