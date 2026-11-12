# Password recovery and password visibility

Added by `sadqah-password-security-update.zip`. Nothing here sends e-mail until you configure SMTP, and nothing here sends SMS at all.

## What it does

| Piece | Where |
|---|---|
| Show / hide password (eye button) on sign-in, registration, account settings (current, new, repeat, delete confirmation) and recovery | `frontend/src/components/ui/PasswordInput.tsx` |
| "Forgot your password?" page: ask for a code, then enter code + new password | `/forgot-password` |
| Admin-initiated reset (administrators only) | `/admin/recovery`, tab "Password resets" |
| API | `GET /auth/recovery/options`, `POST /auth/password-reset/request`, `POST /auth/password-reset/confirm`, `POST /admin/users/password-reset` |
| Database | `database/patches/002_password_recovery.sql` (one table, five new functions, and one replaced function: `api.fn_set_my_password_hash`), tests in `database/tests/password_recovery.sql` and the two-session test `database/tests/password_recovery_concurrency.sh` |

## Security design

* **Codes**: 8 digits from Python's `secrets`. Only an HMAC (server-keyed, bound to the e-mail address) is stored, never the code.
* **One use, expiry, attempts**: a code works once, expires after `RECOVERY_CODE_TTL_SECONDS` (default 15 min), and dies after 5 wrong guesses. This is decided inside PostgreSQL under a row lock (`api.fn_pr_redeem`), so attempts cannot be raced. A newer code replaces the older one.
* **Concurrent requests**: issuing a code first locks the person's `users` row (`FOR NO KEY UPDATE`), then checks the cooldown, the hourly cap and the open code. Two simultaneous requests (self-service or admin, in any mix) therefore queue: the first issues a code, the second finds it and gets the same empty/`too_soon` answer as any throttled request, never a database error. Redeeming and changing a password take the same lock first, so lock order is always users then password_resets (no deadlocks). The one-open-code unique index stays as a last-resort guard.
* **Password change closes codes**: `api.fn_set_my_password_hash` (Settings > Change password) also closes any recovery code still open for that person, and the audit row records how many.
* **Admin identity**: `core.fn_admin_start_reset` refuses unless the administrator it is given is the signed-in user of that database transaction (`core.current_user_id()`), on top of the role check.
* **Rate limits**: per client address, per e-mail address (counted whether or not the account exists), and in the database (60 s between codes, 5 per hour per account), so the database limits still hold if Redis is down.
* **No account enumeration**: "request" gives the same 202 answer for known, unknown, inactive and throttled accounts, and the e-mail is sent after the answer so timing does not differ. "confirm" gives one 400 message for every failure and always spends one Argon2 hash. The only non-uniform answers are server-wide: 503 "e-mail is not set up" and 429 rate limits.
* **Passwords**: hashed with the project's existing Argon2id (`hash_password`), checked with the existing `password_problem` policy. A successful reset also clears the failed-login count and any lockout. It does not sign anyone in.
* **Contact encryption**: e-mail addresses stay encrypted at rest; they are decrypted only in memory to send the message.
* **Admin-initiated reset**: `require_admin` in the API, and again inside `core.fn_admin_start_reset` (which runs on the `admin` database role). Reviewers, recipients and donors are refused. The code goes only to the verified e-mail on record; the administrator never sees the code, the address or the password. Admin accounts cannot be targeted, and nobody can target themselves. Every attempt is written to the audit log (actions `password_reset.*`) without codes, addresses or hashes.
* **Delivery failure**: the code is closed, the failure is audited (`password_reset.delivery_failed`, with the exception class only), and the server log never contains an address or secret.

## What "verified e-mail" means here (read this)

SadQah has no e-mail verification step at registration, and before this update nothing ever set `email_verified_at` except the demo seed script. So:

* **Self-service recovery** works for any active account with a registered e-mail. A successful reset proves the person controls the inbox, so the account's e-mail is then marked verified.
* **Admin-initiated reset** only works for accounts whose e-mail is already verified (from a successful self-service reset, or the seed data). For anyone else the console says "no eligible account" and nothing is sent. This is deliberate: sending a code to an unverified address could hand an account to whoever owns a mistyped address. If you want admin resets to work for everyone, add a registration e-mail verification step first.

## Configuration

Set in your private `.env` (placeholders are in `.env.example`; nothing secret is in the update):

```
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=SadQah <no-reply@your-domain>
APP_BASE_URL=https://your-site        # already used elsewhere; the e-mail links to <APP_BASE_URL>/forgot-password
```

With `SMTP_HOST` empty, `/forgot-password` shows "not set up yet" and the API answers 503. For your own domain, set up SPF/DKIM/DMARC with your mail provider or the codes will land in spam. Outside `ENV=dev`, `SMTP_SECURITY=none` is refused at start-up.

## SMS (off)

`app/services/mailer.py` defines an `SmsProvider` interface and an empty `SMS_PROVIDERS` registry. With `SMS_PROVIDER=none` (the default), the API reports `sms: false` from `/auth/recovery/options` and refuses `channel: "sms"`. To add one later: implement `SmsProvider.send`, register it under a name, set `SMS_PROVIDER=<name>`. The database already supports an `sms` channel but only for accounts with a verified phone (`phone_verified_at`), and nothing in the project sets that yet.

## Known limits

* Sessions are stateless JWTs and cannot be revoked, so a password reset does not sign out sessions that already exist; they expire on their own (12 h, staff 1 h). This was already true of "change password".
* Anyone who knows an e-mail address can request codes for it (up to 3 per hour from the web tier, 5 per hour in the database). They cannot read the codes, but they can fill the owner's inbox within those limits.
* The per-address limiter fails open if Redis is down (existing project behaviour); the database limits and the 5-attempt cap do not.
* The Python route tests run the handlers against a scripted database; real PostgreSQL behaviour is tested separately in SQL. Neither tests a real SMTP server, real FastAPI request handling or real Argon2 here.
