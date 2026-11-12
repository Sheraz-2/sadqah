# SadQah: security notes

Scope: what the system defends, where each defence lives, and what an operator must do. Sandbox only today; the
"before going live" list at the end is mandatory for any real-money deployment.

## 1. Assets and threats

| Asset | Main threats | Primary defence |
|---|---|---|
| Recipient identity (name, NIC, phone, address, documents, selfie) | Database leak, insider browsing, API bugs | Field encryption (AES-256-GCM, per-field AAD labels), column-level grants, masked `api.*` views, private vault, audited reviewer access |
| Donor identity and anonymous gifts | De-anonymisation, token theft | Anonymous gifts store only a peppered hash of the Donation Token; no link to any account exists |
| Money movement | Payout redirected, double payout, forged webhook | Destination locked after review, one-row-per-donation queue with `SKIP LOCKED`, `PayPal-Request-Id` idempotency, verified + de-duplicated webhooks, append-only ledger |
| Sessions | XSS, CSRF, fixation | httpOnly `sq_session` JWT, `SameSite=Lax`, double-submit CSRF (`sq_csrf` echoed as `X-CSRF-Token`), strict CSP, short staff TTL |
| Uploads | Malware, polyglots, decompression bombs | Type sniffing, re-encoding of images, pixel cap, optional ClamAV scan, files stored under random keys, served with `nosniff` and a locked-down CSP |

## 2. Database is the authority

* Five logins, none a superuser: `sadqah_api`, `sadqah_worker`, `sadqah_webhook`, `sadqah_kyc`, `sadqah_admin`
  (`database/roles.sql`). The API role has **no usage on the `core` schema**; it reaches data only through `api.*`
  views and functions, so an SQL bug in the API cannot read raw PII.
* Business rules (income under $50/month, allocation range, one active campaign, payout destination lock, ledger
  immutability) are constraints and triggers, so they hold even if application code is wrong.
* Reviewer access to a KYC document is recorded by `fn_audit_kyc_document_view` **before** the bytes are returned.
* The AI pipeline only *recommends* (`needs_human_review`). Approval is a human action through `core.fn_review_kyc`.

## 3. Cryptography and secrets

* `ENCRYPTION_KEYS` (`id:base64`, comma separated) with `ACTIVE_KEY_ID`; rotate by adding a new key, switching the
  active id, and re-encrypting at leisure. Never delete an old key while rows still use it.
* `BLIND_INDEX_KEY` makes e-mail/phone/NIC/receiver lookups possible without storing plaintext. Changing it means
  recomputing every index.
* `TOKEN_PEPPER` protects Donation Tokens; changing it invalidates all anonymous tokens.
* `JWT_SECRET` ≥ 32 random characters. `python backend/scripts/generate_secrets.py` produces all of them.
* `ENV=staging|prod` refuses to start on development defaults, short or default secrets, or missing PayPal/Redis settings
  (`Settings` validator). Secrets belong in a secret manager or an untracked `.env`; the repo contains none.
* Logs never contain tokens, e-mail addresses, document content or request bodies.

## 4. Web layer

* Uniform error shape; duplicate registration returns a generic 409 (no account enumeration beyond that).
* Rate limits (Redis in staging/prod; in-process in dev) on registration, login, tracking-token lookup and public reads.
  Tracking lookups are also limited per token hash to stop guessing.
* Next.js sets CSP, `X-Frame-Options: DENY`, `nosniff`, HSTS and a restrictive Permissions-Policy.
  The only third-party script origin is PayPal.
* Cookies are `Secure` outside `ENV=dev`.
* **Known limitation:** sessions are stateless JWTs; logout clears the cookie but there is no server-side revocation list.
  Mitigate with short TTLs (`SESSION_TTL_MINUTES`, `STAFF_SESSION_TTL_MINUTES`) or add a `sessions` table before launch.

## 5. Payments

* Capture is confirmed server-side; the donation row exists before the PayPal order and its id travels in `custom_id`.
* Webhooks: signature verified with PayPal, event id recorded once, processing idempotent. Failures are stored and retried
  by the reconciler instead of being dropped.
* A PayPal call that times out is treated as *unknown outcome* and retried with the same `PayPal-Request-Id`, never with a fresh one.
* Sandbox cannot pay phone receivers, so sandbox payouts are e-mail only.

## 6. Operator runbook

* **Suspected key leak:** generate new keys, add as the active key, re-encrypt, remove the old key only after verifying
  no rows reference it. For `JWT_SECRET`: rotate and accept that everyone is signed out.
* **Suspicious payout:** pause the payout worker, inspect `/admin/payouts` and `/admin/ledger`, requeue only after review (`/admin/payouts/{id}/requeue`, admin role only).
* **Malware flagged on an upload:** the upload is rejected and nothing is stored; check `CLAMAV_HOST` health if everything is rejected.
* **Reviewer misconduct:** every document view is in the audit log; revoke the staff user's role in the database.

## 7. Before going live (not done in this repo)

1. Independent security review and penetration test; dependency audit (`pip-audit`, `npm audit`) with pinned, reviewed versions.
2. Real KYC/AML and sanctions-screening obligations, privacy policy, data-retention and deletion process, and legal review for each country served.
3. PayPal live-account approval for Payouts; set `PAYPAL_ENV=live` deliberately.
4. Managed Postgres with TLS, backups and PITR; managed Redis; S3 with SSE and bucket policies; ClamAV running.
5. TLS everywhere, correct `TRUSTED_PROXY_COUNT`, WAF/CDN, monitoring and alerting on payout failures and webhook backlog.
6. Session revocation, MFA for staff, and an on-call incident process.

## Update 2: account deletion, assistant, reports

- **Account deletion is a tombstone.** Donations have RESTRICT foreign keys and the ledger and audit log are append-only,
  so the user row is kept but emptied: email, phone, password hash, name, identity fields and documents are wiped, the account
  is inactive, and the public profile and campaigns are closed or anonymised. A recipient with gifts in flight (initiated,
  captured) or payouts not yet settled cannot delete until they are done. Staff cannot self-delete. Sessions are stateless
  JWTs, so an old cookie is refused on its next call (the user is no longer active) and new gifts from a deleted donor are refused.
- **The assistant is advisory.** Prices are model estimates with a stated range; the arithmetic that flags an ask above
  the range is plain code, not the model. The proof check can only raise a request's priority, never lower it. Only a staff
  decision changes a status. The model gets no tools and no access to accounts or payments. Uploaded proof is re-encoded,
  malware-scanned and stored encrypted; every staff view is audited before the bytes are read.
- **Voice** uses the browser's speech recognition. Chrome sends audio to its speech service; SadQah receives only text.
