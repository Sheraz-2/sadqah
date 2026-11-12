// Pure maths for the Giving Calculator. Integer cents everywhere; the donor's income never leaves the browser.

export const STARTER_GRANT_CENTS = 5000; // matches the smallest "exit poverty" allocation (kyc_allocation_min_cents)
export const MIN_PERCENT = 1;
export const MAX_PERCENT = 5;
export const PLEDGE_MIN_CENTS = 100; // mirrors donor_pledges CHECK (>= $1)
export const PLEDGE_MAX_CENTS = 500_000; // mirrors donor_pledges CHECK (<= $5,000)

export type Frequency = "one_time" | "monthly" | "yearly";

/** Yearly gift in cents for an income in whole dollars and a percentage (1 - 5, halves allowed). */
export function yearlyGiftCents(incomeDollars: number, percent: number): number {
  if (!Number.isFinite(incomeDollars) || incomeDollars <= 0) return 0;
  // dollars * percent / 100 dollars  ==  dollars * percent cents
  return Math.round(incomeDollars * percent);
}

export function monthlyFromYearly(yearlyCents: number): number {
  return Math.round(yearlyCents / 12);
}

export function dailyFromYearly(yearlyCents: number): number {
  return Math.round(yearlyCents / 365);
}

export function starterGrants(yearlyCents: number): number {
  return Math.floor(yearlyCents / STARTER_GRANT_CENTS);
}

/** Amount a single payment of this plan would be, for the chosen frequency. */
export function paymentCents(yearlyCents: number, frequency: Frequency): number {
  return frequency === "monthly" ? monthlyFromYearly(yearlyCents) : yearlyCents;
}

export function pledgeAmountProblem(cents: number): string | null {
  if (cents < PLEDGE_MIN_CENTS) return "A plan needs at least $1 per payment.";
  if (cents > PLEDGE_MAX_CENTS) return "A single payment can be at most $5,000. Choose monthly, or a smaller share.";
  return null;
}

export function parseDollars(raw: string): number {
  const n = Number(raw.replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) ? n : 0;
}
