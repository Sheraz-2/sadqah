// Staff-console types. Mirror docs/API_CONTRACT.md (Staff section). Staff never receive donor identity.
import type { KycCase, KycDocType } from "@/types/api";

export type { Flag, KycCase } from "@/types/api";

export type AdminOverview = {
  kyc_waiting: number;
  batches_open: number;
  payouts_needing_attention: number;
  messages_pending: number;
  gratitude_pending: number;
  reconciliation_ok: boolean;
};

export type KycCaseDetail = KycCase & {
  identity: { full_name: string; date_of_birth: string; id_number_masked: string; address: string; doc_country: string | null };
  documents: { id: string; doc_type: KycDocType; mime_type: string; size_bytes: number; scan_status: string; uploaded_at: string }[];
};

export type Batch = {
  id: string;
  sender_batch_id: string;
  paypal_payout_batch_id: string | null;
  status: string;
  item_count: number;
  total_cents: number;
  attempt_count: number;
  next_attempt_at: string | null;
  last_error: string | null;
  created_at: string;
  submitted_at: string | null;
  completed_at: string | null;
};

export type PayoutItem = {
  id: string;
  donation_id: string;
  recipient_id: string;
  amount_cents: number;
  status: string;
  batch_id: string | null;
  paypal_transaction_status: string | null;
  failure_reason: string | null;
  queued_at: string;
  settled_at: string | null;
  next_attempt_at: string | null;
  /** Queued rows only (null for every other status): why it has not been sent yet. */
  eligibility: "ready" | "waiting" | "kyc_blocked" | null;
};

export type LedgerEvent = {
  id: number;
  event_type: string;
  donation_id: string | null;
  payout_queue_id: string | null;
  batch_id: string | null;
  recipient_id: string | null;
  amount_cents: number | null;
  source: string | null;
  external_event_id: string | null;
  details: unknown;
  created_at: string;
};

export type ReconRow = {
  campaign_id: string;
  raised_cents: number;
  paid_out_cents: number;
  donations_captured_cents: number;
  payout_queued_cents: number;
  payout_in_flight_cents: number;
  payout_unclaimed_cents: number;
  payout_problem_cents: number;
  payout_delivered_cents: number;
  raised_mismatch: boolean;
  paid_out_mismatch: boolean;
};

export type QueuedMessage = { id: string; donation_id: string; sender: "donor" | "recipient"; body: string; created_at: string };
export type QueuedGratitude = { id: string; recipient_id: string; is_community: boolean; body: string; created_at: string };
