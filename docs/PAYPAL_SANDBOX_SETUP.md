# PayPal Sandbox setup

SadQah is built for the **PayPal Developer Sandbox** (`PAYPAL_ENV=sandbox`, API base `https://api-m.sandbox.paypal.com`).
No real funds move. Keep credentials in `.env` (git-ignored) or your secret manager, never in the repository.

## 1. Accounts

1. Sign in at <https://developer.paypal.com> → **Apps & Credentials** → toggle **Sandbox**.
2. **Sandbox accounts**: use the default *Business* account as the platform (it receives donations and funds payouts)
   and the default *Personal* account as a test donor. Create further *Personal* accounts as test recipients; use the
   e-mail address of a sandbox personal account for `payout_destination` when testing a real payout.
3. Add funds to the business account (Sandbox accounts → account → *Fund account*) so Payouts can succeed.

## 2. REST app

1. **Apps & Credentials → Create App** (type *Merchant*), pick the business account.
2. Under *Features*, make sure **Payouts** is enabled for the app. (If the Payouts toggle is missing, the sandbox
   business account needs Payouts enabled; PayPal documents this on the developer site.)
3. Copy **Client ID** → `PAYPAL_CLIENT_ID`, **Secret** → `PAYPAL_CLIENT_SECRET`.
   The Client ID is also sent to the browser by `GET /api/v1/public/config` (it is public by design); the secret never leaves the backend.

## 3. Webhook

1. In the same app → **Webhooks → Add Webhook**.
2. URL: `https://<your-tunnel-or-host>/api/v1/webhooks/paypal` (HTTPS is required; use a tunnel for local work).
3. Subscribe to: `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.PENDING`,
   `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.PAYOUTSBATCH.*` (SUCCESS, DENIED, PROCESSING) and
   `PAYMENT.PAYOUTS-ITEM.*` (SUCCEEDED, FAILED, HELD, UNCLAIMED, RETURNED, BLOCKED, REFUNDED, DENIED, CANCELED).
4. Copy the **Webhook ID** → `PAYPAL_WEBHOOK_ID`. The API verifies every delivery's signature with PayPal
   (`verify-webhook-signature`) and de-duplicates by event id before it touches the ledger.

## 4. Sandbox behaviour to know

* **Payout recipient type**: PayPal's sandbox Payouts does not support phone recipients, so the backend sends
  payouts to e-mail receivers in sandbox. Phone/PayPal-ID receivers are only used when `PAYPAL_ENV=live`.
* Sandbox events can arrive late or out of order. The reconciler worker polls batches older than
  `RECONCILE_STALE_AFTER_SECONDS` and settles them idempotently.
* A payout to an e-mail with no PayPal account shows as *Unclaimed*; the donation stays "in transit" until claimed
  or returned.
* Test cards are not needed: pay with the sandbox personal account's PayPal login in the popup.

## 5. Smoke test (once credentials are set)

1. Start the stack (see README). Open <http://localhost:3000/campaigns>, pick a campaign, **Give**, and pay with the sandbox personal account.
2. Save the Donation Token, then open `/track` and paste it: the gift appears as *received*.
3. Lower `PAYOUT_MIN_ITEMS_TO_FIRE`/`PAYOUT_MAX_WAIT_SECONDS` in `.env` (for example 1 and 60) so the payout worker fires quickly.
4. Watch `/admin/payouts` and `/admin/ledger` (staff login) as the batch is submitted and webhooks settle it.
5. Seeded demo recipients have fictional payout destinations; for a real sandbox payout, register a recipient through `/register` and `/recipient/verify` using a sandbox personal e-mail, approve it as the reviewer, and give to it.

Going live is deliberately not covered here: it needs a PayPal business review, `PAYPAL_ENV=live`, and the checklist in `docs/SECURITY.md`.
