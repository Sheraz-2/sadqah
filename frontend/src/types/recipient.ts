// Recipient-portal types. RecipientMe itself lives in types/api.ts (shared with the contract); the rest are portal-only.
import type { KycDocType } from "@/types/api";

export type { RecipientMe, KycDocType, KycMissing } from "@/types/api";

export type RecipientDonation = {
  donation_id: string;
  campaign_slug: string;
  donor_label: string;
  is_anonymous: boolean;
  amount_cents: number;
  delivery_state: string;
  captured_at: string;
  paid_out_at: string | null;
  has_gratitude: boolean;
};

export type Thread = {
  thread_id: string;
  donor_label: string;
  amount_cents: number;
  paid_out_at: string | null;
  last_message_at: string | null;
  unread_count: number;
};

export type ThreadMessageDto = { id: string; sender: "donor" | "recipient"; body: string; status: "approved" | "pending" | "rejected"; created_at: string };

export type Liveness = { challenge_token: string; code: string; expires_at: string };

export const DOC_LABELS: Record<KycDocType, string> = {
  national_id: "National ID card",
  passport: "Passport",
  utility_bill: "Utility bill (proof of address)",
  selfie: "Live selfie with your code",
  bank_statement: "Bank or mobile-money statement",
  proof_of_income: "Other proof of income",
};

export type KindWord = { id: string; campaign_slug: string; author_name: string; body: string; created_at: string };
