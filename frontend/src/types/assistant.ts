export type PriceStatus = "ok" | "high" | "very_high" | "low" | "unknown";

export type PricedItem = {
  index: number;
  name: string;
  quantity: number;
  asked_unit_price: number;
  asked_total: number;
  category: string;
  unit: string;
  low: number | null;
  typical: number | null;
  high: number | null;
  confidence: number;
  note: string;
  status: PriceStatus;
  flags: string[];
  recommended_unit_price: number | null;
};

export type PriceSummary = {
  asked_total_local: number;
  typical_total_local: number | null;
  suggested_total_local: number;
  usd_per_local: number | null;
  asked_total_usd_cents: number | null;
  typical_total_usd_cents: number | null;
  suggested_total_usd_cents: number | null;
  suggested_goal_usd_cents: number | null;
  approved_allocation_cents: number | null;
  unpriced_items: number[];
  flags: string[];
};

export type PriceCheck = {
  ai_available: boolean;
  country: string;
  currency: string;
  items: PricedItem[];
  summary: PriceSummary;
  disclaimer: string;
};

export type NeedsRequest = {
  id: string;
  status: "submitted" | "approved" | "declined" | "more_info";
  country: string;
  currency: string | null;
  items: Partial<PricedItem>[];
  requested_total_cents: number;
  estimated_total_cents: number | null;
  has_proof: boolean;
  reviewer_note: string | null;
  created_at: string;
};
