"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ApiError, get } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatUsd, parseDollarsToCents } from "@/lib/format";
import { useAuth } from "@/hooks/useAuth";
import { useAsync } from "@/hooks/useAsync";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { Spinner } from "@/components/ui/Spinner";
import { PayPalPay } from "./PayPalPay";
import { TokenReveal } from "./TokenReveal";
import type { CaptureResponse, PublicConfig } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  campaign: { slug: string; title: string; recipientName: string; remainingCents: number };
  /** Cents carried over from the giving calculator, if any. */
  initialAmountCents?: number | null;
  /** Called after a gift is confirmed so the page can refresh totals. */
  onGiven: () => void;
};

type Stage = "choose" | "pay" | "thanks";

/** Why this amount cannot be used, or null when it is fine. */
export function amountProblem(cents: number, cfg: PublicConfig, remainingCents: number): string | null {
  if (!Number.isInteger(cents) || cents <= 0) return "Enter an amount, for example 5 or 12.50.";
  if (cents < cfg.min_donation_cents) return `The smallest gift is ${formatUsd(cfg.min_donation_cents)}.`;
  if (cents > cfg.max_donation_cents) return `The largest single gift is ${formatUsd(cfg.max_donation_cents)}.`;
  if (cents > remainingCents) return `Only ${formatUsd(remainingCents)} is still needed. Thank you for wanting to give more.`;
  return null;
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "campaign_unavailable") return "This campaign is not taking gifts right now. It may have just reached its goal.";
    if (err.code === "amount_out_of_range") return err.fields?.amount_cents ?? err.message;
    if (err.code === "payment_failed") return "PayPal could not complete that payment. You have not been charged. Please try again or use another payment method.";
    if (err.code === "rate_limited") return "Too many attempts. Please wait a moment and try again.";
    return err.message;
  }
  return "Something went wrong with the payment. You have not been charged unless PayPal tells you otherwise.";
}

export function DonateModal({ open, onClose, campaign, initialAmountCents, onGiven }: Props) {
  const { me } = useAuth();
  const cfg = useAsync<PublicConfig>((signal) => get<PublicConfig>("/public/config", signal), []);
  const [stage, setStage] = useState<Stage>("choose");
  const [amountText, setAmountText] = useState("");
  const [isAnonymous, setIsAnonymous] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CaptureResponse | null>(null);
  const [token, setToken] = useState<{ value: string; unconfirmed: boolean } | null>(null);

  // Start from a clean slate each time the modal opens.
  useEffect(() => {
    if (!open) return;
    setStage("choose");
    setError(null);
    setResult(null);
    setAmountText(initialAmountCents ? String(initialAmountCents / 100) : "");
  }, [open, initialAmountCents]);

  // Signed-in donors default to a public gift (it earns leaderboard points); everyone else to an anonymous one.
  useEffect(() => {
    setIsAnonymous(!me);
  }, [me, open]);

  const cents = useMemo(() => parseDollarsToCents(amountText), [amountText]);
  const config = cfg.data;
  const problem = config && amountText ? amountProblem(cents, config, campaign.remainingCents) : null;
  const canPay = !!config && !problem && cents > 0 && (isAnonymous || !!me);

  const presets = (config?.presets_cents ?? []).filter((p) => p <= campaign.remainingCents);

  function finish(capture: CaptureResponse, newToken: string | null) {
    setResult(capture);
    onGiven();
    if (capture.is_anonymous && newToken) {
      setToken({ value: newToken, unconfirmed: false });
      onClose(); // the full-screen token screen takes over
    } else {
      setStage("thanks");
    }
  }

  function failed(err: unknown, newToken: string | null) {
    if (newToken) {
      setToken({ value: newToken, unconfirmed: true });
      onClose();
      return;
    }
    setError(errorText(err));
    setStage("choose");
  }

  return (
    <>
      <Modal open={open} onClose={onClose} title={stage === "thanks" ? "Thank you" : `Give to ${campaign.recipientName}`}>
        {stage === "thanks" && result ? (
          <div className="space-y-4">
            <p className="text-lg">
              Your {formatUsd(result.amount_cents)} gift to <strong>{campaign.recipientName}</strong> was received.
            </p>
            {result.points_awarded ? (
              <Alert tone="ok">You earned {result.points_awarded} leaderboard {result.points_awarded === 1 ? "point" : "points"}.</Alert>
            ) : null}
            <p className="text-ink-soft">
              It joins the next verified payout batch. Follow it from <Link href="/dashboard" className="font-semibold underline">your giving page</Link>, and you may get a thank-you back.
            </p>
            <Button onClick={onClose} className="w-full">
              Close
            </Button>
          </div>
        ) : (
          <div className="space-y-6">
            <p className="text-ink-soft">{campaign.title}</p>

            {cfg.loading && !config ? <Spinner label="Loading giving options" /> : null}
            {cfg.error && !config ? <Alert tone="bad">We could not load the giving options. Please close this and try again.</Alert> : null}

            {config && (
              <>
                <fieldset>
                  <legend className="text-base font-semibold">Amount (USD)</legend>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {presets.map((p) => {
                      const on = p === cents;
                      return (
                        <button
                          key={p}
                          type="button"
                          aria-pressed={on}
                          onClick={() => setAmountText(String(p / 100))}
                          className={cn(
                            "h-11 rounded-full px-5 text-base font-semibold ring-1 ring-inset transition-colors",
                            on ? "bg-lapis-900 text-white ring-lapis-900" : "bg-white text-lapis-900 ring-line hover:bg-lapis-50",
                          )}
                        >
                          {formatUsd(p)}
                        </button>
                      );
                    })}
                  </div>
                  <Input
                    className="mt-3"
                    label="Or choose your own"
                    inputMode="decimal"
                    autoComplete="off"
                    placeholder="e.g. 7.50"
                    value={amountText}
                    onChange={(e) => {
                      setAmountText(e.target.value);
                      setError(null);
                    }}
                    error={problem}
                    hint={`${formatUsd(config.min_donation_cents)} to ${formatUsd(Math.min(config.max_donation_cents, campaign.remainingCents))}`}
                  />
                </fieldset>

                <fieldset>
                  <legend className="text-base font-semibold">How would you like to give?</legend>
                  <div className="mt-2 grid gap-3 sm:grid-cols-2">
                    <ModeCard
                      selected={!isAnonymous}
                      onSelect={() => setIsAnonymous(false)}
                      title="Publicly"
                      body="Your display name appears on the campaign and you earn leaderboard points."
                    />
                    <ModeCard
                      selected={isAnonymous}
                      onSelect={() => setIsAnonymous(true)}
                      title="Anonymously"
                      body="No account needed. You get a private token to follow your gift. No one sees your name."
                    />
                  </div>
                  {!isAnonymous && !me && (
                    <Alert tone="warn" className="mt-3">
                      A public gift needs an account.{" "}
                      <Link href={`/login?next=${encodeURIComponent(`/campaigns/${campaign.slug}`)}`} className="font-semibold underline">
                        Sign in
                      </Link>{" "}
                      or{" "}
                      <Link href={`/register?role=donor&next=${encodeURIComponent(`/campaigns/${campaign.slug}`)}`} className="font-semibold underline">
                        create one
                      </Link>
                      , or choose to give anonymously.
                    </Alert>
                  )}
                </fieldset>

                {error && <Alert tone="bad">{error}</Alert>}

                {stage === "choose" ? (
                  <Button variant="give" size="lg" className="w-full" disabled={!canPay} onClick={() => { setError(null); setStage("pay"); }}>
                    {cents > 0 && !problem ? `Continue with ${formatUsd(cents)}` : "Continue"}
                  </Button>
                ) : (
                  <div>
                    <div className="mb-3 flex items-center justify-between rounded-xl bg-lapis-50 px-4 py-3">
                      <span>
                        {formatUsd(cents)} · {isAnonymous ? "anonymous" : "public"}
                      </span>
                      <button type="button" className="font-semibold text-lapis-700 underline" onClick={() => setStage("choose")}>
                        Change
                      </button>
                    </div>
                    <PayPalPay
                      clientId={config.paypal_client_id}
                      currency={config.currency}
                      args={{ campaignSlug: campaign.slug, amountCents: cents, isAnonymous }}
                      onCaptured={finish}
                      onError={failed}
                      onCancel={() => {
                        setError("The payment was cancelled. You have not been charged.");
                        setStage("choose");
                      }}
                    />
                    {config.paypal_env === "sandbox" && <p className="mt-3 text-sm text-ink-soft">Sandbox mode: no real money moves. Pay with a PayPal sandbox account.</p>}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </Modal>
      {token && (
        <TokenReveal
          token={token.value}
          unconfirmed={token.unconfirmed}
          amountLabel={result ? formatUsd(result.amount_cents) : formatUsd(cents)}
          onDone={() => setToken(null)}
        />
      )}
    </>
  );
}

function ModeCard({ selected, onSelect, title, body }: { selected: boolean; onSelect: () => void; title: string; body: string }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn("rounded-2xl p-4 text-left ring-1 ring-inset transition-colors", selected ? "bg-lapis-50 ring-2 ring-lapis-700" : "bg-white ring-line hover:bg-lapis-50")}
    >
      <span className="block text-lg font-semibold">{title}</span>
      <span className="mt-1 block text-base text-ink-soft">{body}</span>
    </button>
  );
}
