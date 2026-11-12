// Mirrors docs/API_CONTRACT.md. Money is always integer cents (USD). Keep in sync with the backend.

export type Role = "donor" | "recipient" | "reviewer" | "admin";

export type Me = {
  id: string;
  role: Role;
  email: string;
  phone: string | null;
  display_name: string | null;
  country_code: string | null;
  show_on_leaderboard: boolean;
};

export type Recipient = {
  slug: string;
  name: string;
  business_type: string | null;
  region_country: string;
  region_admin1: string | null;
};

export type CampaignCard = {
  slug: string;
  title: string;
  excerpt: string;
  cover_url: string | null;
  goal_cents: number;
  raised_cents: number;
  remaining_cents: number;
  percent_funded: number; // 0-100
  donor_count: number;
  status: "active" | "funded";
  recipient: Recipient;
  created_at: string;
};

export type CampaignDetail = CampaignCard & {
  story: string;
  updates: { id: string; body: string; media_urls: string[]; created_at: string }[];
  recent_gifts: { label: string; amount_cents: number; is_anonymous: boolean; given_at: string }[];
  comments: { id: string; author_name: string; body: string; media_url: string | null; created_at: string }[];
};

export type DeliveryState =
  | "queued_for_next_batch"
  | "being_prepared"
  | "on_its_way"
  | "awaiting_recipient_claim"
  | "delivered"
  | "needs_attention";

export type PublicConfig = {
  paypal_client_id: string;
  paypal_env: "sandbox" | "live";
  currency: "USD";
  min_donation_cents: number;
  max_donation_cents: number;
  presets_cents: number[];
};

export type PublicStats = {
  recipients_supported: number;
  countries_reached: number;
  gifts_given: number;
  total_given_cents: number;
};

export type LeaderboardRow = {
  rank: number;
  donor_label: string;
  country_code: string | null;
  points: number;
  donation_count: number;
};

export type GratitudeItem = {
  id: string;
  recipient_name: string;
  campaign_slug: string;
  thanks_to: string;
  body: string;
  created_at: string;
};

export type Pledge = {
  kind: "percent_of_income" | "fixed_amount";
  percent: number | null;
  amount_cents: number;
  frequency: "one_time" | "monthly" | "yearly";
  default_anonymous: boolean;
};

export type CreateOrderResponse = { donation_id: string; paypal_order_id: string; tracking_token: string | null };
export type CaptureResponse = {
  donation_id: string;
  status: "captured";
  amount_cents: number;
  is_anonymous: boolean;
  points_awarded: number | null;
};

export type MyDonation = {
  id: string;
  campaign_slug: string;
  campaign_title: string;
  amount_cents: number;
  status: string;
  created_at: string;
  paid_out_at: string | null;
  thread_open: boolean;
};

export type DonorThread = {
  donation_id: string;
  campaign_slug: string;
  campaign_title: string;
  recipient_name: string;
  donation_status: "captured" | "paid_out";
  thread_open: boolean;
  paid_out_at: string | null;
  last_message_at: string | null;
  unread_count: number;
};

export type DonorThreadMessage = { id: string; sender: "donor" | "recipient"; body: string; status: "approved" | "pending" | "rejected"; created_at: string };

export type TrackView = {
  donation: {
    amount_cents: number;
    given_at: string;
    status: "captured" | "paid_out";
    delivery_state: DeliveryState;
    thread_open: boolean;
  };
  campaign: { slug: string; title: string };
  recipient: { slug: string; name: string; region_country: string; region_admin1: string | null };
  updates: { id: string; body: string; media_urls: string[]; visibility: "public" | "donors"; created_at: string }[];
  messages: { id: string; sender: "donor" | "recipient"; body: string; status: "approved" | "pending" | "rejected"; created_at: string }[];
  gratitude: { body: string; created_at: string } | null;
};

export type KycDocType = "national_id" | "passport" | "utility_bill" | "selfie" | "bank_statement" | "proof_of_income";
export type KycMissing =
  | "identity_details_and_consent"
  | "national_id_or_passport"
  | "utility_bill"
  | "selfie"
  | "bank_statement_or_proof_of_income";

export type RecipientMe = {
  profile: {
    slug: string;
    public_name: string;
    story: string;
    business_type: string | null;
    region_country: string;
    region_admin1: string | null;
    profile_public: boolean;
  } | null;
  kyc: {
    status: "not_started" | "documents_pending" | "processing" | "needs_human_review" | "approved" | "rejected" | "suspended";
    rejection_reason: string | null;
    approved_allocation_cents: number | null;
    identity_saved: boolean;
    documents: { doc_type: KycDocType; uploaded_at: string; scan_status: "pending" | "clean" | "infected" | "failed" }[];
    missing: KycMissing[];
  } | null;
  payout: { type: "EMAIL" | "PHONE"; handle_masked: string } | null;
  campaign: {
    slug: string;
    title: string;
    goal_cents: number;
    raised_cents: number;
    paid_out_cents: number;
    status: "draft" | "active" | "funded" | "closed";
  } | null;
  balance: {
    raised_cents: number;
    queued_cents: number;
    in_flight_cents: number;
    unclaimed_cents: number;
    delivered_cents: number;
    problem_cents: number;
  } | null;
};

export type Flag = { code: string; severity: "info" | "warning" | "critical"; detail: string };
export type KycCase = {
  recipient_id: string;
  status: string;
  income_monthly_usd_cents: number | null;
  face_match: number | null;
  fraud_risk: number | null;
  flags: Flag[];
  recommended_allocation_cents: number | null;
  assessed_at: string | null;
  created_at: string;
};
