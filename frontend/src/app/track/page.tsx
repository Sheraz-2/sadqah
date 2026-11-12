"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { ApiError, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDate, formatUsd, regionLabel } from "@/lib/format";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Field";
import { ThreadView } from "@/components/messaging/ThreadView";
import type { DeliveryState, TrackView } from "@/types/api";

const POLL_MS = 10_000;

const STEPS: { state: DeliveryState; label: string; body: string }[] = [
  { state: "queued_for_next_batch", label: "Received", body: "Your gift is safely recorded and waiting for the next payout batch." },
  { state: "being_prepared", label: "Being prepared", body: "It is being grouped into a payout batch with other verified gifts." },
  { state: "on_its_way", label: "On its way", body: "The payout has been sent through PayPal." },
  { state: "awaiting_recipient_claim", label: "Waiting to be claimed", body: "PayPal is waiting for the recipient to accept the money. They have been invited to." },
  { state: "delivered", label: "Delivered", body: "The money reached the recipient." },
];

/** Tokens are typed by people: spaces, dashes and case do not matter, so we only trim. The server normalises it. */
export default function TrackPage() {
  const [input, setInput] = useState("");
  const [view, setView] = useState<TrackView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // The token is held in memory only: never in the URL, local storage or cookies.
  const tokenRef = useRef<string | null>(null);

  const lookup = useCallback(async (token: string, quiet = false) => {
    if (!quiet) {
      setLoading(true);
      setError(null);
    }
    try {
      const v = await post<TrackView>("/track/lookup", { token });
      tokenRef.current = token;
      setView(v);
      setError(null);
    } catch (err) {
      if (quiet) return; // a background refresh failing is not worth interrupting the reader
      tokenRef.current = null;
      setView(null);
      setError(
        err instanceof ApiError && err.status === 404
          ? "We could not find a gift for that token. Check it for typing mistakes and try again."
          : err instanceof ApiError
            ? err.message
            : "Something went wrong. Please try again.",
      );
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  // Refresh about every 10 seconds, only while a token is held and the tab is visible.
  useEffect(() => {
    if (!view) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible" && tokenRef.current) void lookup(tokenRef.current, true);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [view, lookup]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = input.trim();
    if (t) void lookup(t);
  }

  function forget() {
    tokenRef.current = null;
    setView(null);
    setInput("");
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
      <h1 className="text-5xl font-bold">Track a gift</h1>
      <p className="mt-4 text-lg text-ink-soft">
        Gave anonymously? Enter the Donation Token you saved. We do not keep your name, so the token is the only way to follow the gift. Gave while signed in? Your gifts are on{" "}
        <Link href="/dashboard" className="font-semibold underline">your giving page</Link>.
      </p>

      {!view ? (
        <form onSubmit={submit} className="mt-8 space-y-4">
          <Input
            label="Donation Token"
            placeholder="SQ-XXXX-XXXX-…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            maxLength={80}
            className="[&_input]:font-mono"
            error={error}
            hint="Dashes, spaces and capital letters do not matter."
          />
          <Button type="submit" size="lg" loading={loading} disabled={!input.trim()}>
            Find my gift
          </Button>
        </form>
      ) : (
        <TrackResult view={view} onSend={async (body) => {
          if (!tokenRef.current) return;
          await post("/track/messages", { token: tokenRef.current, body });
          await lookup(tokenRef.current, true);
        }} onForget={forget} />
      )}
    </div>
  );
}

function TrackResult({ view, onSend, onForget }: { view: TrackView; onSend: (body: string) => Promise<void>; onForget: () => void }) {
  const { donation: d, recipient: r } = view;
  const idx = STEPS.findIndex((s) => s.state === d.delivery_state);
  const attention = d.delivery_state === "needs_attention";

  return (
    <div className="mt-8 space-y-8">
      <Card>
        <p className="text-sm font-semibold uppercase tracking-wide text-ink-soft">Your gift</p>
        <p className="mt-1 font-display text-4xl font-bold">{formatUsd(d.amount_cents)}</p>
        <p className="mt-1 text-ink-soft">
          to <Link href={`/campaigns/${view.campaign.slug}`} className="font-semibold text-lapis-700 underline">{view.campaign.title}</Link> · {r.name}, {regionLabel(r.region_country, r.region_admin1)} · given {formatDate(d.given_at)}
        </p>
      </Card>

      <section aria-labelledby="progress-h">
        <h2 id="progress-h" className="text-3xl font-semibold">Where it is</h2>
        {attention ? (
          <Alert tone="warn" title="This gift needs a little extra care" className="mt-4">
            Your money is safe and recorded. Something about the payout needs a human to look at it, and our team has been alerted. You do not need to do anything.
          </Alert>
        ) : (
          <ol className="mt-5 space-y-3">
            {STEPS.map((s, i) => {
              const done = i < idx || d.delivery_state === "delivered";
              const current = i === idx && d.delivery_state !== "delivered";
              return (
                <li key={s.state} className={cn("flex gap-4 rounded-2xl p-4 ring-1", current ? "bg-lapis-50 ring-lapis-500" : "bg-paper ring-line", !done && !current && "opacity-60")}>
                  <span
                    aria-hidden
                    className={cn("mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-bold", done ? "bg-tile-500 text-white" : current ? "bg-lapis-700 text-white" : "bg-lapis-100 text-ink-soft")}
                  >
                    {done ? "✓" : i + 1}
                  </span>
                  <div>
                    <p className="font-semibold">
                      {s.label}
                      {current && <span className="ml-2 text-sm font-medium text-lapis-700">(now)</span>}
                    </p>
                    {(current || (i === STEPS.length - 1 && done)) && <p className="text-ink-soft">{s.body}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {view.gratitude && (
        <section aria-labelledby="thanks-h" className="rounded-2xl bg-saffron-100 p-6">
          <h2 id="thanks-h" className="text-2xl font-semibold">A thank-you from {r.name}</h2>
          <p className="mt-2 whitespace-pre-wrap break-words text-lg">{view.gratitude.body}</p>
        </section>
      )}

      {view.updates.length > 0 && (
        <section aria-labelledby="upd-h">
          <h2 id="upd-h" className="text-3xl font-semibold">Updates from {r.name}</h2>
          <ol className="mt-4 space-y-4">
            {view.updates.map((u) => (
              <li key={u.id} className="rounded-2xl bg-paper p-5 ring-1 ring-line">
                <p className="text-sm text-ink-soft">{formatDate(u.created_at)}{u.visibility === "donors" && " · for donors"}</p>
                <p className="mt-1 whitespace-pre-wrap break-words">{u.body}</p>
                {u.media_urls.map((m) => (
                  <img key={m} src={m} alt={`Photo from ${r.name}`} loading="lazy" className="mt-3 rounded-xl" />
                ))}
              </li>
            ))}
          </ol>
        </section>
      )}

      <section aria-labelledby="msg-h">
        <h2 id="msg-h" className="text-3xl font-semibold">Messages</h2>
        <p className="mb-4 mt-1 text-ink-soft">{r.name} will never see who you are. Messages are reviewed before they are delivered.</p>
        <ThreadView
          messages={view.messages}
          viewerRole="donor"
          canPost={d.thread_open}
          lockedText="Messaging opens once your gift has been delivered."
          onSend={onSend}
          otherPartyLabel={r.name}
        />
      </section>

      <Button variant="ghost" onClick={onForget}>
        Look up a different token
      </Button>
    </div>
  );
}
