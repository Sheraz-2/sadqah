"use client";

import Link from "next/link";
import { useId, useMemo, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { errorMessage, put } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatNumber, formatUsd } from "@/lib/format";
import {
  MAX_PERCENT,
  MIN_PERCENT,
  STARTER_GRANT_CENTS,
  dailyFromYearly,
  monthlyFromYearly,
  paymentCents,
  parseDollars,
  pledgeAmountProblem,
  starterGrants,
  yearlyGiftCents,
  type Frequency,
} from "@/lib/giving";
import { buttonClass } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { Star } from "@/components/ui/Star";
import type { Pledge } from "@/types/api";

type Mode = "percent" | "custom";
const PLEDGE_CAP = 50_000; // one gift is capped at $500 by default (max_donation_cents); the campaign page enforces the live limit
const MAX_STARS = 30;
const FREQ: { id: Frequency; label: string }[] = [
  { id: "monthly", label: "Every month" },
  { id: "yearly", label: "Once a year" },
  { id: "one_time", label: "One time" },
];

export function GivingCalculator({ compact = false }: { compact?: boolean }) {
  const { me } = useAuth();
  const incomeId = useId();
  const customId = useId();
  const rangeId = useId();

  const [income, setIncome] = useState("40000");
  const [mode, setMode] = useState<Mode>("percent");
  const [percent, setPercent] = useState(2.5);
  const [custom, setCustom] = useState("300");
  const [frequency, setFrequency] = useState<Frequency>("monthly");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const incomeDollars = parseDollars(income);

  const yearlyCents = useMemo(() => {
    if (mode === "percent") return yearlyGiftCents(incomeDollars, percent);
    // A custom amount is "per payment" in the chosen frequency; convert to a yearly equivalent for the summary.
    const entered = Math.round(parseDollars(custom) * 100);
    return frequency === "monthly" ? entered * 12 : entered;
  }, [mode, incomeDollars, percent, custom, frequency]);

  const perPayment = mode === "custom" ? Math.round(parseDollars(custom) * 100) : paymentCents(yearlyCents, frequency);
  const grants = starterGrants(yearlyCents);
  const shownStars = Math.min(grants, MAX_STARS);
  const sharePct = incomeDollars > 0 ? (yearlyCents / (incomeDollars * 100)) * 100 : null;
  const problem = yearlyCents > 0 ? pledgeAmountProblem(perPayment) : "Enter an amount to see your plan.";

  async function savePlan() {
    setSaving(true);
    setError(null);
    try {
      const body =
        mode === "percent"
          ? { kind: "percent_of_income", percent, amount_cents: perPayment, frequency, default_anonymous: false }
          : { kind: "fixed_amount", amount_cents: perPayment, frequency, default_anonymous: false };
      await put<Pledge>("/me/pledge", body);
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={cn("overflow-hidden rounded-3xl bg-white ring-1 ring-line", !compact && "shadow-[var(--shadow-lift)]")}>
      <div className="grid lg:grid-cols-[1.05fr_1fr]">
        {/* ---------------------------------------------------------------- controls */}
        <div className="space-y-7 p-6 sm:p-9">
          <div>
            <label htmlFor={incomeId} className="block text-base font-semibold">
              Your yearly income
            </label>
            <div className="relative mt-2">
              <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-soft">$</span>
              <input
                id={incomeId}
                inputMode="numeric"
                autoComplete="off"
                value={income}
                onChange={(e) => {
                  setIncome(e.target.value);
                  setSaved(false);
                }}
                className="w-full rounded-xl border-0 py-3 pl-8 pr-4 text-xl ring-1 ring-inset ring-line focus:ring-2 focus:ring-lapis-500"
              />
            </div>
            <p className="mt-1.5 text-sm text-ink-soft">Total before tax, in US dollars. This stays in your browser. We never see it.</p>
          </div>

          <div role="radiogroup" aria-label="How to choose your amount" className="grid grid-cols-2 gap-1 rounded-full bg-lapis-50 p-1">
            {(
              [
                ["percent", "A share of my income"],
                ["custom", "An amount I choose"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={mode === id}
                onClick={() => {
                  setMode(id);
                  setSaved(false);
                }}
                className={cn("rounded-full px-3 py-2.5 text-base font-semibold transition-colors", mode === id ? "bg-white text-lapis-900 shadow-sm" : "text-ink-soft hover:text-lapis-900")}
              >
                {label}
              </button>
            ))}
          </div>

          {mode === "percent" ? (
            <div>
              <div className="flex items-baseline justify-between">
                <label htmlFor={rangeId} className="text-base font-semibold">
                  Share of your income
                </label>
                <output htmlFor={rangeId} className="font-display text-4xl font-bold text-lapis-900">
                  {percent}%
                </output>
              </div>
              <input
                id={rangeId}
                type="range"
                className="sq-range mt-4"
                min={MIN_PERCENT}
                max={MAX_PERCENT}
                step={0.5}
                value={percent}
                onChange={(e) => {
                  setPercent(Number(e.target.value));
                  setSaved(false);
                }}
                aria-valuetext={`${percent} percent of yearly income`}
              />
              <div className="mt-2 flex justify-between text-sm text-ink-soft" aria-hidden>
                <span>1% a gentle start</span>
                <span>3% balanced</span>
                <span>5% committed</span>
              </div>
            </div>
          ) : (
            <div>
              <label htmlFor={customId} className="block text-base font-semibold">
                Amount per payment
              </label>
              <div className="relative mt-2">
                <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-soft">$</span>
                <input
                  id={customId}
                  inputMode="decimal"
                  autoComplete="off"
                  value={custom}
                  onChange={(e) => {
                    setCustom(e.target.value);
                    setSaved(false);
                  }}
                  className="w-full rounded-xl border-0 py-3 pl-8 pr-4 text-xl ring-1 ring-inset ring-line focus:ring-2 focus:ring-lapis-500"
                />
              </div>
              <p className="mt-1.5 text-sm text-ink-soft">Any amount from $1. Change it whenever you like.</p>
            </div>
          )}

          <fieldset>
            <legend className="text-base font-semibold">How often</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {FREQ.map((f) => (
                <label
                  key={f.id}
                  className={cn(
                    "cursor-pointer rounded-full px-4 py-2 text-base font-medium ring-1 ring-inset transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-saffron-400",
                    frequency === f.id ? "bg-lapis-900 text-white ring-lapis-900" : "bg-white text-ink ring-line hover:bg-lapis-50",
                  )}
                >
                  <input
                    type="radio"
                    name="frequency"
                    className="sr-only"
                    checked={frequency === f.id}
                    onChange={() => {
                      setFrequency(f.id);
                      setSaved(false);
                    }}
                  />
                  {f.label}
                </label>
              ))}
            </div>
          </fieldset>
        </div>

        {/* ---------------------------------------------------------------- result */}
        <div className="pattern-stars relative bg-lapis-900 p-6 text-white sm:p-9" aria-live="polite">
          <p className="text-lapis-100">Your plan comes to</p>
          <p className="mt-1 font-display text-5xl font-bold tracking-tight sm:text-6xl">
            {yearlyCents > 0 ? formatUsd(yearlyCents) : "$0"}
            <span className="ml-2 text-xl font-medium text-lapis-100">a year</span>
          </p>
          <dl className="mt-4 grid grid-cols-3 gap-3 text-base">
            <div>
              <dt className="text-lapis-100/80">Per month</dt>
              <dd className="text-xl font-semibold">{formatUsd(monthlyFromYearly(yearlyCents), { cents: false })}</dd>
            </div>
            <div>
              <dt className="text-lapis-100/80">Per day</dt>
              <dd className="text-xl font-semibold">{formatUsd(dailyFromYearly(yearlyCents), { cents: true })}</dd>
            </div>
            <div>
              <dt className="text-lapis-100/80">Of income</dt>
              <dd className="text-xl font-semibold">{sharePct === null ? "–" : `${sharePct.toFixed(sharePct < 10 ? 1 : 0)}%`}</dd>
            </div>
          </dl>

          <div className="mt-7 border-t border-white/15 pt-6">
            <p className="text-lg">
              {grants > 0 ? (
                <>
                  That could fund <strong className="text-saffron-400">{formatNumber(grants)}</strong> starter {grants === 1 ? "grant" : "grants"} of {formatUsd(STARTER_GRANT_CENTS)} for
                  people who live on less than $50 a month.
                </>
              ) : (
                <>Every {formatUsd(STARTER_GRANT_CENTS)} you give starts a verified person on a small business. Keep going: even part of one grant counts.</>
              )}
            </p>
            <div className="mt-4 flex flex-wrap gap-1.5" role="img" aria-label={`${grants} starter grants`}>
              {Array.from({ length: shownStars }, (_, i) => (
                <Star key={i} className="size-7 text-saffron-400" />
              ))}
              {grants > MAX_STARS && <span className="self-center pl-1 text-lapis-100">+{formatNumber(grants - MAX_STARS)} more</span>}
              {grants === 0 && <Star className="size-7 text-saffron-400" lit={false} />}
            </div>
          </div>

          <div className="mt-8 space-y-3">
            {problem && yearlyCents > 0 && <Alert tone="warn">{problem}</Alert>}
            <div className="flex flex-wrap gap-3">
              <Link
                href={`/campaigns?amount=${Math.min(Math.max(perPayment, 0), PLEDGE_CAP)}`}
                className={buttonClass("give", "lg", cn(!!problem && "pointer-events-none opacity-55"))}
                aria-disabled={!!problem}
              >
                Choose who to give to
              </Link>
              {me ? (
                <button type="button" onClick={savePlan} disabled={saving || !!problem} className={buttonClass("secondary", "lg")}>
                  {saved ? "Plan saved" : saving ? "Saving…" : "Save as my giving plan"}
                </button>
              ) : (
                <Link href="/register?role=donor" className={buttonClass("secondary", "lg")}>
                  Create an account to save it
                </Link>
              )}
            </div>
            {error && <Alert tone="bad">{error}</Alert>}
            {saved && <Alert tone="ok">Saved. You can change or remove your plan from your giving dashboard at any time.</Alert>}
          </div>
        </div>
      </div>
    </div>
  );
}
