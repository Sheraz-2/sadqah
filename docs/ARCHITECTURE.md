# SadQah: Architecture & Project Blueprint (Phase 1)

## 1. Stack decision

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js 14+ (App Router, TypeScript) + TailwindCSS + AG Grid Community** | Server components for fast, emotional landing and campaign pages; AG Grid for leaderboard, KYC review queue, ledger and payout-batch screens. |
| Backend | **Python 3.12 + FastAPI** | Chosen over Node/Express because the heaviest work is Python-native: document and image handling (Pillow, pypdf), LLM and vision SDKs, face-match pipelines, and worker/queue logic. FastAPI gives async I/O, Pydantic validation and automatic OpenAPI docs. |
| Database | **PostgreSQL 16** | Row-level security, column-level grants, SECURITY DEFINER functions, triggers and `FOR UPDATE SKIP LOCKED` queues let the *database* enforce privacy and money rules, not only application code. |
| Queue / cache | **Postgres-backed payout queue + Redis** | The payout queue lives in Postgres so it is transactional with the ledger. Redis is used only for rate limiting and short-lived caches. |
| Object storage | **S3-compatible bucket (MinIO locally)** | KYC files are stored encrypted, private, and served only through short-lived signed URLs to reviewers. |
| Payments | **PayPal Developer Sandbox** (Orders v2 for donations, Payouts API for grants, Webhooks for reconciliation) | Matches the hackathon constraint. |

## 2. System overview

```
 Donor browser ──► Next.js ──► FastAPI ──┬─► PayPal Orders v2 (donation capture, in one modal)
                                         │
                                         ├─► PostgreSQL  (ledger, queue, KYC, masked views)
                                         │        ▲
                                         │        │ claims rows (SKIP LOCKED)
                                         ├─► Payout worker ──► PayPal Payouts API (one batch = many grants)
                                         │
                                         ├─► KYC worker ──► LLM / Vision pipeline ──► object storage
                                         │
 PayPal ── webhooks ──► /webhooks/paypal ──► verify signature ──► dedupe ──► reconcile ledger
```

Money path of one donation:

1. Donor clicks Give. The API creates a `donations` row (status `initiated`) with its **UUID and recipient already bound**, and puts that UUID in the PayPal order (`custom_id`).
2. Donor approves in the PayPal modal. API captures the order. Webhook `PAYMENT.CAPTURE.COMPLETED` (or the capture response) moves the donation to `captured`.
3. A trigger writes a `payout_queue` row (status `queued`). **No payout API call happens yet.**
4. The payout worker runs on a schedule, claims queued rows, groups them into one batch, and calls the Payouts API once.
5. PayPal webhooks (`PAYMENT.PAYOUTSBATCH.SUCCESS`, `PAYMENT.PAYOUTS-ITEM.*`) reconcile each item to its donation by `sender_item_id`, append ledger events, update campaign totals, and unlock the tracking and messaging state.

## 3. Directory tree

Legend: **[P1]** delivered in this phase, **[P3]** PayPal batch and webhook backend, **[P4]** KYC and AI pipeline, **[P5]** frontend.

```
sadqah/
├── README.md                                  [P1] Setup, run order, security checklist
├── docker-compose.yml                         [P1] Postgres 16 + Redis + MinIO for local dev
├── .env.example                               [P1] Every variable the stack needs, no secrets
├── .gitignore                                 [P1] Keeps .env, uploads, keys out of git
│
├── docs/
│   ├── ABOUT_SADQAH.md                        [P1] Meaning of the name, appeal, 1-5% giving guide
│   ├── ARCHITECTURE.md                        [P1] This file
│   ├── SECURITY.md                            [P4] Threat model, key rotation, incident runbook
│   └── PAYPAL_SANDBOX_SETUP.md                [P3] Creating sandbox business/personal accounts, enabling Payouts, webhook URL
│
├── database/
│   ├── schema.sql                             [P1] Tables, enums, constraints, triggers, RLS, masked views, definer functions, grants
│   ├── roles.sql                              [P1] Login roles for API, worker, webhook, compliance (passwords from env)
│   └── seed_dev.sql                           [P3] Fake recipients/campaigns for demos
│
├── backend/
│   ├── pyproject.toml                         [P3] Dependencies and tool config
│   ├── Dockerfile                             [P3] Non-root, slim image
│   ├── alembic.ini                            [P3] Migrations config
│   ├── migrations/                            [P3] Versioned changes after schema.sql baseline
│   └── app/
│       ├── main.py                            [P3] FastAPI app, middleware stack, router mounting
│       ├── core/
│       │   ├── config.py                      [P3] Typed settings from env (pydantic-settings)
│       │   ├── security.py                    [P3] JWT, password hashing (argon2), token generation and hashing
│       │   ├── crypto.py                      [P3] AES-256-GCM envelope encryption, blind indexes (HMAC)
│       │   ├── rate_limit.py                  [P3] Redis sliding-window limits, stricter on token and auth endpoints
│       │   ├── db_context.py                  [P3] Sets `app.current_user_id` per request for RLS, picks DB role
│       │   ├── logging.py                     [P3] Structured logs with PII redaction
│       │   └── errors.py                      [P3] Uniform error shape, no stack leakage
│       ├── api/v1/
│       │   ├── auth.py                        [P3] Sign-up, login, email/phone verification
│       │   ├── campaigns.py                   [P3] Public campaign list and detail (masked views only)
│       │   ├── donations.py                   [P3] Create donation, capture order, issue one-time Donation Token
│       │   ├── pledges.py                     [P3] Giving calculator and 1-5% pledges
│       │   ├── tracking.py                    [P3] Token exchange, recipient region, updates (never donor identity)
│       │   ├── messages.py                    [P3] Anonymous moderated messaging, both directions
│       │   ├── gratitude.py                   [P3] Recipient thank-yous
│       │   ├── leaderboard.py                 [P3] Public donors only
│       │   ├── recipients.py                  [P4] Recipient sign-up and profile
│       │   ├── kyc.py                         [P4] Secure document upload, status polling
│       │   ├── admin.py                       [P4] Review queue, approve/reject, batch overview
│       │   └── webhooks.py                    [P3] PayPal webhook endpoint
│       ├── schemas/                           [P3] Pydantic request/response models, one file per router
│       ├── services/
│       │   ├── paypal_client.py               [P3] OAuth token cache, Orders and Payouts calls, retries
│       │   ├── payout_batcher.py              [P3] Claims queue rows, builds and submits batches, exponential backoff
│       │   ├── ledger.py                      [P3] Append-only events and reconciliation logic
│       │   ├── webhook_verifier.py            [P3] PayPal signature verification and dedupe
│       │   ├── token_service.py               [P3] Donation Token creation and lookup
│       │   ├── moderation.py                  [P3] Blocks contact details and abuse in messages
│       │   ├── file_vault.py                  [P4] Validates, scans, encrypts and stores uploads
│       │   └── kyc/
│       │       ├── pipeline.py                [P4] Orchestrates the steps below
│       │       ├── extractor.py               [P4] Vision/LLM extraction from ID, bills, statements
│       │       ├── face_match.py              [P4] Selfie vs ID photo score
│       │       ├── income_analyzer.py         [P4] Monthly income and the <$50 check
│       │       ├── fraud_scoring.py           [P4] Duplicate NIC, doc tampering, inconsistency flags
│       │       └── allocation.py              [P4] Exit-poverty capital recommendation
│       ├── workers/
│       │   ├── payout_worker.py               [P3] Scheduled loop that runs payout_batcher
│       │   ├── reconciler.py                  [P3] Sweeps stale batches and polls PayPal for missed webhooks
│       │   └── kyc_worker.py                  [P4] Processes KYC jobs asynchronously
│       └── tests/                             [P3] pytest: anonymity leaks, ledger balance, retry logic
│
└── frontend/
    ├── package.json                           [P5]
    ├── next.config.mjs                        [P5] Security headers and CSP
    ├── tailwind.config.ts                     [P5] Warm, human design tokens
    ├── tsconfig.json                          [P5]
    └── src/
        ├── middleware.ts                      [P5] Auth gating for portal and admin routes
        ├── app/
        │   ├── layout.tsx                     [P5] Shell, fonts, providers
        │   ├── page.tsx                       [P5] Landing: hero story, live impact counter, About SadQah
        │   ├── about/page.tsx                 [P5] Renders ABOUT_SADQAH content
        │   ├── give/page.tsx                  [P5] Giving calculator (1-5% slider or custom amount)
        │   ├── campaigns/page.tsx             [P5] Browse and filter by region
        │   ├── campaigns/[slug]/page.tsx      [P5] Story, progress bar, updates, comments, single-modal donate
        │   ├── leaderboard/page.tsx           [P5] AG Grid of public donors
        │   ├── track/page.tsx                 [P5] Anonymous token entry (token never placed in the URL)
        │   ├── dashboard/                     [P5] Donor history (AG Grid), pledges, messages
        │   ├── recipient/                     [P5] Portal: onboarding, KYC upload, dashboard, thank-you
        │   └── admin/                         [P5] KYC review, payout batches, ledger (AG Grid)
        ├── components/
        │   ├── donate/DonateModal.tsx         [P5] One modal: amount, public/anonymous, PayPal buttons
        │   ├── donate/TokenReveal.tsx         [P5] Shows the Donation Token once, with copy and download
        │   ├── campaign/ProgressBar.tsx       [P5] Animated, honest progress
        │   ├── campaign/CommentThread.tsx     [P5] Media-rich community comments
        │   ├── kyc/DocumentUploader.tsx       [P5] Client-side checks, progress, retry
        │   ├── messaging/ThreadView.tsx       [P5] Anonymous chat view
        │   └── grids/                         [P5] AG Grid wrappers and column definitions
        ├── lib/                               [P5] API client, formatters, PayPal SDK loader
        ├── hooks/                             [P5]
        └── types/                             [P5] Types mirroring backend schemas
```

## 4. How the three failure constraints are engineered

### Constraint 1: AML and gateway collapse under spikes

- **Decouple intake from payout.** Capturing a donation only writes a database row. The expensive, scrutinised cross-border step (Payouts) never runs inline with a donor's click.
- **`payout_queue` with an explicit state machine:** `queued → batched → submitted → succeeded | failed | unclaimed | returned`. A trigger rejects illegal transitions.
- **Batching:** the worker claims up to N rows with `FOR UPDATE SKIP LOCKED`, so several workers can run safely without double-paying, and groups them into **one Payouts batch**. Multiple grants to the same recipient in the same batch are summed into one item to reduce item count.
- **Idempotency:** each batch has a unique `sender_batch_id` stored *before* the API call. If the process crashes after the call, the retry reuses the same id, so PayPal rejects duplicates instead of paying twice.
- **Retries:** exponential backoff with jitter (e.g. 30s, 2m, 8m, 32m, capped), tracked in `attempt_count` and `next_attempt_at`. After the maximum, the batch moves to `failed` and surfaces in the admin grid. Timeouts are treated as *unknown outcome*: the reconciler asks PayPal for the batch status by `sender_batch_id` before ever resubmitting.
- **Smoothing:** a configurable per-run item cap and minimum interval flatten spikes into steady, compliance-friendly flows.
- **Checkout friction is separate:** the donor-facing capture is a standard PayPal order, so 3DS and authentication happen inside PayPal's modal, once.

### Constraint 2: sterile, high-friction experience

- One modal: amount chips ($5 / $10 / $25 / custom), a public-or-anonymous toggle, and PayPal buttons. No account is required to give. Anonymous donors never need to register.
- Campaign pages lead with the person's story, region, photo (optional, consented), a live progress bar, update posts and a comment area.
- The Giving Calculator turns "how much?" into a slider (1% to 5% of income, or a custom amount) with an instant per-month and per-year readout.
- Heavy authentication (KYC) is placed on the **recipient** side, where it protects donors, instead of on donors.

### Constraint 3: reconciliation nightmares

- **Bind before you send:** the donation row (UUID, donor reference or anonymous hash, recipient) exists before PayPal is contacted. The UUID travels as `custom_id` on orders and `sender_item_id` on payout items.
- **Append-only `ledger_events`:** every state change is a new immutable row (update and delete are blocked by trigger). Balances are derived from events.
- **Webhook handling:** verify signature, insert into `webhook_events` with a unique PayPal event id (replays become no-ops), then reconcile in a single transaction. Out-of-order events are safe because transitions are validated.
- **Real-time side effects** (campaign totals, tracking state, message-thread unlock, leaderboard points) are driven by the same transaction, with no manual step.
- **Safety net:** `reconciler.py` periodically checks `submitted` batches older than a threshold against PayPal, in case a webhook never arrived.

## 5. Security model

| Concern | Control |
|---|---|
| PII at rest | Application-level AES-256-GCM envelope encryption (data keys wrapped by a master key from env/KMS) for names, NIC numbers, addresses, phone, message bodies. Stored as `BYTEA`. Disk-level encryption on the DB host and bucket as a second layer. |
| Searching encrypted data | Blind indexes (HMAC-SHA256) for email, phone and NIC, so uniqueness and duplicate-fraud checks work without plaintext. |
| Anonymous donors | No donor id on the row. Token stored only as a hash. Enforced by CHECK constraints and by roles that cannot read the donor columns (see schema). |
| Private DB scopes | Separate login roles for API, worker, webhook handler and compliance, with column-level grants. RLS on user-owned tables. Public data comes only from masked views. |
| File uploads | Size and MIME allow-list, magic-byte check, image re-encoding, EXIF stripping, malware scan hook, random object keys, encrypted storage, signed short-lived URLs, no public bucket. |
| API abuse | Redis sliding-window rate limits (strict on auth, token lookup and uploads), request size limits, CORS allow-list, security headers. |
| Webhooks | PayPal signature verification, replay protection by event id, constant-time compare, no trust in payload amounts (re-fetch when in doubt). |
| AI decisions | AI **recommends**; the DB refuses `approved` KYC without a verified income under the threshold and a recorded reviewer decision. Face-match and fraud scores are inputs for a human reviewer, not the sole authority. |
| Biometrics | Selfies and face-match scores are sensitive biometric data: explicit consent, encryption, defined retention period and deletion path. |

## 6. Anonymous tracking and messaging model

1. When a donor gives anonymously, the server generates a random 256-bit **Donation Token**, shows it **once**, and stores only its hash.
2. The token holder proves possession by sending the token. The server hashes it and looks up the donation through a SECURITY DEFINER function that returns *only* recipient-safe fields: region, public profile, updates, status.
3. Messages are keyed to the donation, not to a person. The recipient sees "A SadQah donor". The donor sees the recipient's public name. Neither side ever receives the other's identity.
4. Message bodies are encrypted at rest and pass moderation (no phone numbers, emails, links or payment requests) before delivery.
5. **Trade-off to be explicit about:** an anonymous token is the only way back. If it is lost, it cannot be recovered, by design. Public donors keep access through their account.
6. PayPal itself necessarily knows the payer. SadQah keeps that reference in an encrypted, compliance-only table, so refunds and legal obligations still work without exposing it to the product APIs.

## 7. PayPal notes for the sandbox

- Create a **sandbox Business** account (platform) and **sandbox Personal** accounts (test donors and recipients). Create an app, enable **Payouts** on it, and register your webhook URL.
- Payout item receivers can be `EMAIL`, `PHONE` or `PAYPAL_ID`. Unclaimed payments are returned to the sender after a holding period, which is why `unclaimed` and `returned` states exist in the queue.
- Webhook events used: `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.PAYOUTSBATCH.PROCESSING`, `PAYMENT.PAYOUTSBATCH.SUCCESS`, `PAYMENT.PAYOUTSBATCH.DENIED`, and `PAYMENT.PAYOUTS-ITEM.SUCCEEDED / UNCLAIMED / RETURNED / FAILED / BLOCKED / HELD / REFUNDED`.
- PayPal limits the number of items per batch. Confirm the current limit in the Payouts docs and set `PAYOUT_MAX_ITEMS_PER_BATCH` below it.
- Production note: this build is sandbox-only. PayPal's availability for businesses in Pakistan is limited, so before going live, check with PayPal which country and legal entity can operate Payouts.

## 8. Build order

1. **P1 (now):** workspace, docs, schema, roles.
2. **P3:** backend core, PayPal client, batcher, worker, webhook handler, donation and tracking endpoints.
3. **P4:** recipient portal API, secure uploads, KYC pipeline, admin review.
4. **P5:** Next.js frontend with AG Grid screens, donate modal, calculator, tracking and messaging UI.
