# SadQah HTTP API contract (v1)

Single source of truth shared by `backend/` (FastAPI) and `frontend/` (Next.js).
Base path: `/api/v1`. The frontend reaches it same-origin through a Next.js rewrite
(`/api/:path*` -> `${BACKEND_URL}/api/:path*`), so cookies are first-party.

## Conventions

- JSON, `snake_case`. Money is always an **integer number of cents** (USD only). Never floats.
- IDs are UUID strings. Timestamps are ISO-8601 UTC strings.
- **Auth** is an httpOnly cookie `sq_session` (set by login/register). The API also sets a readable cookie
  `sq_csrf`. For every non-GET request the client must echo it in the header `X-CSRF-Token`
  (the backend rejects cookie-authenticated writes without it). Always call with `credentials: "include"`.
- **Errors** always have this shape, with the matching HTTP status:
  `{"error": {"code": "snake_case_code", "message": "Human readable", "fields": {"field": "problem"}?}}`
  Codes used by the UI: `unauthenticated` (401), `forbidden` (403), `not_found` (404), `validation_error` (422),
  `rate_limited` (429, has `Retry-After`), `message_rejected` (422), `campaign_unavailable` (409),
  `amount_out_of_range` (422), `conflict` (409), `payment_failed` (402), `upstream_unavailable` (503).
- Roles: `donor`, `recipient`, `reviewer`, `admin`.
- **Anonymity rule the UI must respect:** nothing in any response ever contains the identity of an anonymous donor.
  The anonymous "Donation Token" is shown **once** (returned by `POST /donations/orders`) and is never put in a URL;
  tracking uses `POST` with the token in the body.

## Types

```ts
type Me = { id: string; role: "donor"|"recipient"|"reviewer"|"admin"; email: string; phone: string|null;
            display_name: string|null; country_code: string|null; show_on_leaderboard: boolean };

type Recipient = { slug: string; name: string; business_type: string|null;
                   region_country: string; region_admin1: string|null };

type CampaignCard = { slug: string; title: string; excerpt: string; cover_url: string|null;
  goal_cents: number; raised_cents: number; remaining_cents: number; percent_funded: number /* 0-100 */;
  donor_count: number; status: "active"|"funded"; recipient: Recipient; created_at: string };

type CampaignDetail = CampaignCard & {
  story: string;
  updates: { id: string; body: string; media_urls: string[]; created_at: string }[];
  recent_gifts: { label: string; amount_cents: number; is_anonymous: boolean; given_at: string }[];
  comments: { id: string; author_name: string; body: string; media_url: string|null; created_at: string }[];
};

type DeliveryState = "queued_for_next_batch"|"being_prepared"|"on_its_way"|"awaiting_recipient_claim"|"delivered"|"needs_attention";
```

## Auth and account

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/register` | `{email, password (min 12 chars), display_name?, country_code?, phone?, role: "donor"\|"recipient"}` | `201 {user: Me}` + cookies |
| POST | `/auth/login` | `{email, password}` | `{user: Me}` + cookies |
| POST | `/auth/logout` | – | `204` |
| GET | `/auth/me` | – | `Me` (401 if no session) |
| PATCH | `/me` | `{display_name?, show_on_leaderboard?}` | `Me` |

Rate limits: auth endpoints are strict (429 with `Retry-After`).

## Public (no login)

| Method | Path | Response |
|---|---|---|
| GET | `/public/config` | `{paypal_client_id, paypal_env: "sandbox"\|"live", currency: "USD", min_donation_cents, max_donation_cents, presets_cents: number[]}` |
| GET | `/public/stats` | `{recipients_supported, countries_reached, gifts_given, total_given_cents}` |
| GET | `/public/campaigns?q=&country=&sort=newest\|almost_funded\|most_supported&limit=12&offset=0` | `{items: CampaignCard[], total}` |
| GET | `/public/campaigns/{slug}` | `CampaignDetail` |
| GET | `/public/leaderboard?limit=50` | `{items: {rank, donor_label, country_code: string\|null, points, donation_count}[]}` |
| GET | `/public/gratitude?limit=20` | `{items: {id, recipient_name, campaign_slug, thanks_to, body, created_at}[]}` |
| GET | `/media/{key}` | image bytes (public campaign images only) |

`POST /campaigns/{slug}/comments` (login required) `{body}` -> `{id, status: "approved"|"pending"}`.

## Donating (one modal, PayPal)

Flow: `create order` -> PayPal buttons approve in the modal -> `capture`. No account is needed to give
**anonymously**; a public gift needs a signed-in donor (it earns leaderboard points).

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/donations/orders` | `{campaign_slug, amount_cents, is_anonymous}` | `{donation_id, paypal_order_id, tracking_token: string\|null}` (token only when `is_anonymous`; keep it in memory and show it after capture succeeds) |
| POST | `/donations/orders/{paypal_order_id}/capture` | – | `{donation_id, status: "captured", amount_cents, is_anonymous, points_awarded: number\|null}` |
| GET | `/me/donations` | – | `{items: {id, campaign_slug, campaign_title, amount_cents, status, created_at, paid_out_at: string\|null, thread_open}[]}` |
| GET | `/me/gratitude` | – | `{items: {id, donation_id, recipient_name, body, created_at}[]}` |
| GET | `/me/pledge` | – | `Pledge \| null` |
| PUT | `/me/pledge` | `{kind: "percent_of_income"\|"fixed_amount", percent?: 1..5, amount_cents, frequency: "one_time"\|"monthly"\|"yearly", default_anonymous}` | `Pledge` |
| DELETE | `/me/pledge` | – | `204` |

`Pledge = {kind, percent: number|null, amount_cents, frequency, default_anonymous}`. The donor's income is never sent
to the server: the Giving Calculator works the amount out in the browser, then the donor picks a campaign to give to.

Errors on create: `campaign_unavailable` (409, not active / fully funded), `amount_out_of_range` (422; `fields.amount_cents`
tells the allowed range, and for a nearly funded campaign the remaining amount).

## Anonymous tracking and messaging (token holder)

The token looks like `SQ-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-CCCC` (base32; last group is a checksum).
Whitespace and dashes are ignored; case-insensitive. A wrong token always returns the same generic `404 not_found`.
Strictly rate limited. Poll `lookup` every ~10 s while the tab is visible to see delivery and replies appear.

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/track/lookup` | `{token}` | `TrackView` |
| POST | `/track/messages` | `{token, body (1-1000 chars)}` | `{id, status: "approved"\|"pending"}` |

```ts
type TrackView = {
  donation: { amount_cents: number; given_at: string /* date */; status: "captured"|"paid_out";
              delivery_state: DeliveryState; thread_open: boolean };
  campaign: { slug: string; title: string };
  recipient: { slug: string; name: string; region_country: string; region_admin1: string|null };
  updates: { id: string; body: string; media_urls: string[]; visibility: "public"|"donors"; created_at: string }[];
  messages: { id: string; sender: "donor"|"recipient"; body: string; status: "approved"|"pending"; created_at: string }[];
  gratitude: { body: string; created_at: string } | null;
};
```
Messages are only possible when `thread_open` (the gift has been delivered). Contact details (phone, e-mail, links)
are rejected by moderation with `message_rejected` and `message` explaining why. Messages are moderated: the
sender sees their own message with `status: "pending"` until it is approved.

## Recipient portal (role `recipient`)

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/recipient/profile` | `{public_name, story?, business_type?, region_country (ISO-2), region_admin1?, payout_type: "EMAIL"\|"PHONE", payout_handle}` | `201 RecipientMe` |
| GET | `/recipient/me` | – | `RecipientMe` (`profile: null` until created) |
| PUT | `/recipient/profile` | `{public_name?, story?, business_type?, region_admin1?}` | `RecipientMe` |
| PUT | `/recipient/payout` | `{payout_type, payout_handle}` | `RecipientMe` (409 once verification is under review/approved) |
| POST | `/recipient/profile/public` | `{public: boolean}` | `RecipientMe` (needs approved KYC) |
| POST | `/recipient/campaign` | `{title, story?, goal_cents}` | `RecipientMe` (needs approved KYC; goal <= approved allocation) |
| POST | `/recipient/updates` | multipart: `body`, `visibility` (`public`\|`donors`), `images[]` (0-4 jpg/png/webp) | `{id}` |
| GET | `/recipient/donations` | – | `{items: {donation_id, campaign_slug, donor_label, is_anonymous, amount_cents, delivery_state, captured_at, paid_out_at: string\|null, has_gratitude}[]}` |

```ts
type KycDocType = "national_id"|"passport"|"utility_bill"|"selfie"|"bank_statement"|"proof_of_income";
type RecipientMe = {
  profile: { slug: string; public_name: string; story: string; business_type: string|null;
             region_country: string; region_admin1: string|null; profile_public: boolean } | null;
  kyc: { status: "not_started"|"documents_pending"|"processing"|"needs_human_review"|"approved"|"rejected"|"suspended";
         rejection_reason: string|null; approved_allocation_cents: number|null; identity_saved: boolean;
         documents: { doc_type: KycDocType; uploaded_at: string; scan_status: "pending"|"clean"|"infected"|"failed" }[];
         missing: ("identity_details_and_consent"|"national_id_or_passport"|"utility_bill"|"selfie"|"bank_statement_or_proof_of_income")[] } | null;
  payout: { type: "EMAIL"|"PHONE"; handle_masked: string } | null;
  campaign: { slug: string; title: string; goal_cents: number; raised_cents: number; paid_out_cents: number;
              status: "draft"|"active"|"funded"|"closed" } | null;
  balance: { raised_cents: number; queued_cents: number; in_flight_cents: number; unclaimed_cents: number;
             delivered_cents: number; problem_cents: number } | null;
};
```

### KYC (strict portal verification)

| Method | Path | Body | Response |
|---|---|---|---|
| PUT | `/recipient/kyc/identity` | `{full_name, date_of_birth (YYYY-MM-DD), id_number, address, doc_country (ISO-2), consent_biometric: true, consent_data: true}` | `RecipientMe` |
| GET | `/recipient/kyc/liveness` | – | `{challenge_token, code, expires_at}` (the selfie must be taken live with this 4-digit code written on paper and visible in the photo; valid 15 min) |
| POST | `/recipient/kyc/documents` | multipart: `doc_type`, `file` (jpg/png/pdf, <= 10 MB), `challenge_token` (required for `selfie`) | `{doc_type, uploaded_at}` |
| POST | `/recipient/kyc/submit` | – | `{status, missing: string[]}` |

After `submit` the status is `processing` (AI assessment, then a human reviewer decides). Poll `GET /recipient/me`.
The AI only recommends; a human approves. Reasons for rejection are shown in `kyc.rejection_reason`.

### Recipient messaging and gratitude

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/recipient/threads` | – | `{items: {thread_id, donor_label, amount_cents, paid_out_at, last_message_at: string\|null, unread_count}[]}` (anonymous donors only; label is always "A SadQah donor") |
| GET | `/recipient/threads/{thread_id}` | – | `{messages: {id, sender, body, status, created_at}[]}` (marks as read) |
| POST | `/recipient/threads/{thread_id}/messages` | `{body}` | `{id, status}` |
| POST | `/recipient/gratitude` | `{donation_id, body (1-1000)}` | `{id, audience: "donor"\|"community", status}` |

`audience` is chosen by the server from the donor's privacy choice: a public donor is thanked directly, an anonymous
donor is thanked as part of the community. The UI must not offer a choice.

## Staff (role `reviewer` or `admin`; `payouts requeue` is admin only)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/admin/overview` | – | `{kyc_waiting, batches_open, payouts_needing_attention, messages_pending, gratitude_pending, reconciliation_ok}` |
| GET | `/admin/kyc/queue` | – | `{items: KycCase[]}` |
| GET | `/admin/kyc/{recipient_id}` | – | `KycCaseDetail` |
| GET | `/admin/kyc/documents/{doc_id}/content` | – | decrypted bytes (`Cache-Control: no-store`); every view is audited |
| POST | `/admin/kyc/{recipient_id}/decision` | `{decision: "approved"\|"rejected"\|"suspended", verified_monthly_income_cents?, approved_allocation_cents?, reason?}` | `{ok: true}` |
| GET | `/admin/payouts/batches?limit=50` | – | `{items: {id, sender_batch_id, paypal_payout_batch_id, status, item_count, total_cents, attempt_count, next_attempt_at, last_error, created_at, submitted_at, completed_at}[]}` |
| GET | `/admin/payouts/queue?status=&limit=200` | – | `{items: {id, donation_id, recipient_id, amount_cents, status, batch_id, paypal_transaction_status, failure_reason, queued_at, settled_at}[]}` |
| POST | `/admin/payouts/{payout_id}/requeue` | – | `{ok: true}` |
| GET | `/admin/ledger?after_id=&limit=200` | – | `{items: {id, event_type, donation_id, payout_queue_id, batch_id, recipient_id, amount_cents, source, external_event_id, details, created_at}[]}` |
| GET | `/admin/reconciliation` | – | `{ok: boolean, items: {campaign_id, raised_cents, paid_out_cents, donations_captured_cents, payout_queued_cents, payout_in_flight_cents, payout_unclaimed_cents, payout_problem_cents, payout_delivered_cents, raised_mismatch, paid_out_mismatch}[]}` |
| GET | `/admin/moderation/messages` | – | `{items: {id, donation_id, sender, body, created_at}[]}` |
| POST | `/admin/moderation/messages/{id}` | `{decision: "approved"\|"rejected", reason?}` | `{ok: true}` |
| GET | `/admin/moderation/gratitude` | – | `{items: {id, recipient_id, is_community, body, created_at}[]}` |
| POST | `/admin/moderation/gratitude/{id}` | `{decision: "approved"\|"rejected"}` | `{ok: true}` |

```ts
type Flag = { code: string; severity: "info"|"warning"|"critical"; detail: string };
type KycCase = { recipient_id: string; status: string; income_monthly_usd_cents: number|null; face_match: number|null;
                 fraud_risk: number|null; flags: Flag[]; recommended_allocation_cents: number|null;
                 assessed_at: string|null; created_at: string };
type KycCaseDetail = KycCase & {
  identity: { full_name: string; date_of_birth: string; id_number_masked: string; address: string; doc_country: string };
  documents: { id: string; doc_type: KycDocType; mime_type: string; size_bytes: number; uploaded_at: string }[];
};
```
Staff screens never show donor identity: the data simply is not available to them.

## Account settings, assistant, trust (added in update 2)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/account/settings` | – | `{role, email, phone, display_name, country_code, show_on_leaderboard, can_delete, delete_blockers: string[]}` |
| POST | `/account/password` | `{current_password, new_password}` | 204 |
| GET | `/account/export` | – | JSON attachment `sadqah-my-data.json` |
| POST | `/account/delete` | `{password, confirm: "DELETE"}` | `{deleted: true, files_erased}`; clears the session cookies. Tombstone, not a row delete (see SECURITY.md). A recipient with gifts in flight, or staff, gets 409 with the reason. |
| POST | `/assistant/chat` | `{messages: {role: "user"\|"assistant", content}[1..14], page?}` | `{reply, ai}`; `ai=false` means the built-in FAQ answered. Anyone, rate limited. |
| POST | `/assistant/price-check` | `{currency, items: {name, quantity, asked_price}[1..20], explanation?}` | `{ai_available, country, currency, items, summary, disclaimer}`; recipients only. Estimates, never quotes. |
| POST | `/assistant/needs` | multipart: `payload` (the same JSON) + `proof` (image or PDF) | `{id, status, message}`; recipients only, 5 per day. The proof is re-encoded, scanned and stored encrypted. |
| GET | `/assistant/needs` | – | `{items: {id, status, country, currency, items, requested_total_cents, estimated_total_cents, has_proof, reviewer_note, created_at}[]}` (the recipient never sees the AI flags) |
| GET | `/public/trust-stats` | – | `{gifts_received, gifts_delivered, raised_cents, delivered_cents, awaiting_payout_cents, platform_fees_cents, refunds, median_payout_seconds}` |
| POST | `/campaigns/{slug}/report` | `{reason: "fake_or_misleading"\|"not_in_need"\|"impersonation"\|"inappropriate"\|"other", details?}` | `{received, message}`; works without an account |
| GET | `/admin/needs` | – | `{items: NeedsCase[]}` open requests, HIGH priority first (staff) |
| GET | `/admin/needs/{id}/proof` | – | the proof file (`no-store`, audited before reading) |
| POST | `/admin/needs/{id}/decision` | `{decision: "approved"\|"declined"\|"more_info", note?}` | `{ok: true}` |
| GET | `/admin/reports` | – | `{items: {id, reason, details, campaign_slug, campaign_title, reports_on_campaign, ...}[]}` |
| POST | `/admin/reports/{id}/resolve` | `{status: "dismissed"\|"actioned"}` | `{ok: true}` |

The proof check returns the strict shape `{hr_filter_status: PASSED|FLAGGED_SUSPICIOUS|FAILED_IRRELEVANT, priority_queue: HIGH|MEDIUM|LOW,
flags_found: string[], notes_for_human_reviewer: string}`. It is advice: only a staff decision changes a status.

## Webhooks and health (server to server)

`POST /webhooks/paypal` (PayPal only, signature verified), `GET /healthz`, `GET /readyz`.
