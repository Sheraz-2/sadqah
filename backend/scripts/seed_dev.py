#!/usr/bin/env python3
# ruff: noqa: S105, S608  (dev-only script: every interpolated value is a constant or passed through q()/hexb(); the demo password is public)
"""DEVELOPMENT ONLY. Fills a fresh local database with a small, clearly FICTIONAL demo world so every page has something to show.

    export PGHOST=localhost PGPORT=5432 PGUSER=postgres          # a superuser/owner connection (NOT the app roles)
    python backend/scripts/seed_dev.py --database sadqah
    python backend/scripts/seed_dev.py --database sadqah --password 'Another-Demo-Pass-1'

What it creates (all names and stories are invented; first names only, no real people, no real PayPal accounts):
  * 1 admin, 1 reviewer, 3 public donors, 8 recipients (PK, BD, KE, NG, EG, ID) with approved verification, public
    profiles, one live campaign each ($120 to $480 goals, partly funded), a few progress updates,
  * a handful of anonymous and public gifts (captured), three delivered gifts with thank-you notes.
Seeded payouts are parked 10 years in the future so a running payout worker never tries to pay the fictional receivers.

Rules: refuses to run unless ENV=dev; idempotent (a second run does nothing); every account shares one demo password that is
printed at the end; e-mail addresses use example.com (reserved, never delivers). Needs `psql` on PATH and the backend's
dependencies (cryptography, argon2-cffi) because secrets are encrypted exactly the way the API does it.
"""
from __future__ import annotations

import argparse
import secrets
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import aad  # noqa: E402
from app.core.crypto import Crypto  # noqa: E402

DEFAULT_PASSWORD = "SadQah-Demo-Pass-2026"
STAFF = (("admin", "admin.demo@example.com", "Demo Admin"), ("reviewer", "reviewer.demo@example.com", "Demo Reviewer"))
DONORS = (("donor1.demo@example.com", "Amina R.", "GB"), ("donor2.demo@example.com", "Daniel K.", "CA"),
          ("donor3.demo@example.com", "Mei L.", "SG"))

# name, country, region, business, title, goal_cents, story, [gift cents...], delivered_count, [update texts]
RECIPIENTS = (
    ("Bilal", "PK", "Punjab", "tailoring", "A second-hand sewing machine for Bilal", 24000,
     "I stitch school uniforms by hand for my neighbours. A treadle machine would let me finish a uniform in an afternoon "
     "instead of three days, and take on orders from two nearby schools.", [2500, 1000, 5000, 1500], 2,
     ["The machine is ordered. I measured my first ten school uniforms this week."]),
    ("Ruqaiyya", "BD", "Sylhet", "home bakery", "A small oven so Ruqaiyya can bake for the market", 36000,
     "I make biscuits in a clay pot over a fire. An electric oven would make every batch the same and let me sell on market days.",
     [5000, 2000, 1000], 1, ["Found a seller two streets away with a good oven. Thank you all."]),
    ("Wanjiru", "KE", "Nakuru", "vegetable stall", "A cool box and scales for Wanjiru's stall", 18000,
     "Half my tomatoes spoil before noon. A cool box and honest scales would cut my losses and my customers' doubts.",
     [1000, 3000, 2500], 1, []),
    ("Chidi", "NG", "Enugu", "phone repair", "Tools for Chidi's phone repair table", 30000,
     "I repair phones on a borrowed table. A proper tool kit and a soldering station would let me take on screen and charger repairs.",
     [2000, 1500], 0, ["Bought the first screwdriver set. Repairs start next week."]),
    ("Hanna", "EG", "Minya", "hand weaving", "Wool and thread for Hanna's loom", 12000,
     "My loom is ready but I cannot afford thread in bulk. Buying wholesale halves my cost per rug.", [4000, 1000], 0, []),
    ("Siti", "ID", "Central Java", "batik", "Wax and dyes for Siti's batik", 21000,
     "I draw batik by hand. Wax and natural dyes are my biggest cost; a monthly supply would let me work every day.",
     [2500, 2500, 1000], 0, ["First batch of wax arrived. Starting a blue and brown series."]),
    ("Imran", "PK", "Sindh", "rickshaw repair", "Repairs to keep Imran's rickshaw on the road", 48000,
     "My rickshaw is my family's only income and it keeps breaking down. A new battery and clutch would keep me working every day.",
     [5000, 3000], 0, []),
    ("Fatima", "KE", "Mombasa", "fish drying", "Drying racks for Fatima's fish", 27000,
     "I dry fish on the ground and lose a third to sand and flies. Raised racks would protect it and let me sell at a better price.",
     [1000, 1500, 2000], 0, []),
)


def q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def hexb(raw: bytes) -> str:
    return "'\\x" + raw.hex() + "'"


def build_sql(crypto: Crypto, hasher: Callable[[str], str], password: str) -> str:
    out: list[str] = ["\\set ON_ERROR_STOP on", "\\set QUIET on", "BEGIN;", "RESET ROLE;"]

    def user_cols(email: str) -> tuple[str, str]:
        return hexb(crypto.encrypt_text(email, aad.USER_EMAIL)), hexb(crypto.blind_index("email", email))

    for role, email, name in STAFF:
        enc, idx = user_cols(email)
        out.append(
            "INSERT INTO core.users (role, email_enc, email_blind_idx, password_hash, display_name, email_verified_at) "
            f"VALUES ({q(role)}, {enc}, {idx}, {q(hasher(password))}, {q(name)}, now()) RETURNING id AS {role}_id \\gset")

    out.append("SET ROLE sadqah_api;")
    for i, (email, name, country) in enumerate(DONORS, 1):
        enc, idx = user_cols(email)
        out.append(f"SELECT api.fn_register_user({enc}, {idx}, NULL, NULL, {q(hasher(password))}, 'donor', {q(name)}, {q(country)}) AS donor{i} \\gset")
    for i, (name, country, *_rest) in enumerate(RECIPIENTS, 1):
        email = f"recipient{i}.demo@example.com"
        enc, idx = user_cols(email)
        out.append(f"SELECT api.fn_register_user({enc}, {idx}, NULL, NULL, {q(hasher(password))}, 'recipient', {q(name)}, {q(country)}) AS ruser{i} \\gset")

    gift_no = 0
    for i, (name, country, region, business, title, goal, story, gifts, delivered, updates) in enumerate(RECIPIENTS, 1):
        slug = f"{name.lower()}-{business.replace(' ', '-')}"
        camp = f"{name.lower()}-campaign"
        payout_email = f"payout{i}.demo@example.com"
        nic = f"DEMO{i:08d}"
        out.append("RESET ROLE; SET ROLE sadqah_api;")
        out.append(f"SELECT set_config('app.current_user_id', :'ruser{i}', false);")
        out.append(
            f"SELECT api.fn_create_recipient_profile({q(slug)}, {q(name)}, {q(story)}, {q(business)}, {q(country)}, {q(region)}, 'EMAIL', "
            f"{hexb(crypto.encrypt_text(payout_email, aad.RECEIVER))}, {hexb(crypto.blind_index('receiver', payout_email))}) AS rec{i} \\gset")
        out.append(
            f"SELECT api.fn_kyc_save_identity({hexb(crypto.encrypt_text(name + ' (fictional)', aad.KYC_FULL_NAME))}, "
            f"{hexb(crypto.encrypt_text('1988-01-01', aad.KYC_DOB))}, {hexb(crypto.encrypt_text(nic, aad.KYC_NIC))}, "
            f"{hexb(crypto.blind_index('nic', nic))}, {hexb(crypto.encrypt_text('Fictional address, ' + region, aad.KYC_ADDRESS))}, {q(country)}, true, true);")
        out.append("RESET ROLE;")  # the assessment and the reviewer decision are not API actions: written as the owner
        out.append(
            "UPDATE core.recipients_kyc SET status = 'approved', verified_monthly_income_cents = 3000, "
            f"approved_allocation_cents = {max(goal, 5000)}, reviewer_id = :'reviewer_id', reviewed_at = now(), ai_assessed_at = now(), "
            "ai_fraud_risk_score = 0.05, ai_face_match_score = 0.95, ai_extracted_monthly_income_cents = 3000, "
            f"ai_model_version = 'seed-demo' WHERE recipient_id = :'rec{i}';")
        out.append("SET ROLE sadqah_api;")
        out.append(f"SELECT set_config('app.current_user_id', :'ruser{i}', false);")
        out.append("SELECT api.fn_set_profile_public(true);")
        out.append(f"SELECT api.fn_create_campaign({q(camp)}, {q(title)}, {q(story)}, {goal});")
        for text in updates:
            out.append(f"SELECT api.fn_post_campaign_update({q(text)}, ARRAY[]::text[], 'public');")

        for n, cents in enumerate(gifts):
            gift_no += 1
            var = f"g{gift_no}"
            out.append("RESET ROLE; SET ROLE sadqah_api;")
            if (gift_no + n) % 3 == 0:  # an anonymous gift: only an (unrecoverable, fictional) token hash exists
                out.append("SELECT set_config('app.current_user_id', '', false);")
                out.append(f"SELECT api.fn_create_donation({q(camp)}, {cents}, true, NULL, {hexb(secrets.token_bytes(32))}) AS {var} \\gset")
            else:
                donor = f"donor{(gift_no % len(DONORS)) + 1}"
                out.append(f"SELECT set_config('app.current_user_id', :'{donor}', false);")
                out.append(f"SELECT api.fn_create_donation({q(camp)}, {cents}, false, :'{donor}', NULL) AS {var} \\gset")
            out.append(f"SELECT api.fn_attach_paypal_order(:'{var}', {q(f'SEED-ORDER-{gift_no}')});")
            out.append(f"RESET ROLE; SELECT core.fn_mark_donation_captured(:'{var}', {q(f'SEED-CAP-{gift_no}')}, {cents}, '\\x00');")
            if n < delivered:
                batch = f"SEED-BATCH-{gift_no}"
                out.append(
                    "INSERT INTO core.payout_batches (sender_batch_id, paypal_payout_batch_id, status, item_count, total_cents, submitted_at, completed_at) "
                    f"VALUES ({q(batch)}, {q('SEED-PP-' + str(gift_no))}, 'success', 1, {cents}, now(), now()) RETURNING id AS b{gift_no} \\gset")
                out.append(f"UPDATE core.payout_queue SET status = 'batched', batch_id = :'b{gift_no}' WHERE donation_id = :'{var}';")
                out.append(f"UPDATE core.payout_queue SET status = 'submitted' WHERE donation_id = :'{var}';")
                out.append(f"UPDATE core.payout_queue SET status = 'succeeded', paypal_transaction_status = 'SUCCESS' WHERE donation_id = :'{var}';")
                out.append("SET ROLE sadqah_api;")
                out.append(f"SELECT set_config('app.current_user_id', :'ruser{i}', false);")
                out.append(f"SELECT api.fn_post_gratitude(:'{var}', {q('Thank you. Because of you my work can continue.')});")
                out.append("RESET ROLE;")
                out.append(f"UPDATE core.gratitude_notes SET moderation_status = 'approved' WHERE donation_id = :'{var}';")
    out.append("RESET ROLE;")
    out.append("UPDATE core.payout_queue SET next_attempt_at = now() + interval '10 years' WHERE status = 'queued';")
    out.append("COMMIT;")
    return "\n".join(out) + "\n"


def psql(args: list[str], sql: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", *args], input=sql, text=True, capture_output=True, check=False)  # noqa: S603,S607


def main(argv: list[str] | None = None, *, hasher: Callable[[str], str] | None = None, crypto: Crypto | None = None,
         env: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default="sadqah")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="shared demo password (min 12 characters)")
    parser.add_argument("--dry-run", action="store_true", help="print the SQL instead of running it")
    args = parser.parse_args(argv)
    if len(args.password) < 12:
        parser.error("--password must be at least 12 characters")

    if crypto is None or env is None or hasher is None:
        from app.core.config import get_settings
        from app.core.crypto import get_crypto
        from app.core.security import hash_password

        settings = get_settings()
        env, crypto, hasher = settings.env, get_crypto(), hash_password
    if env != "dev":
        print("Refusing to run: this script only runs with ENV=dev.", file=sys.stderr)
        return 2

    if args.dry_run:
        print(build_sql(crypto, hasher, args.password))
        return 0
    marker = hexb(crypto.blind_index("email", STAFF[0][1]))
    probe = psql(["-At", "-d", args.database, "-c", f"SELECT count(*) FROM core.users WHERE email_blind_idx = {marker}"])
    if probe.returncode != 0:
        print(probe.stderr.strip() or "Could not reach the database (is psql configured? see the PG* variables).", file=sys.stderr)
        return 1
    if probe.stdout.strip() != "0":
        print("Already seeded: nothing to do.")
        return 0
    result = psql(["-q", "-d", args.database, "-f", "-"], build_sql(crypto, hasher, args.password))
    if result.returncode != 0:
        print("Seeding failed and was rolled back:\n" + result.stderr.strip(), file=sys.stderr)
        return 1
    print("Seeded the fictional demo world.\n\nSign in with the shared demo password below (dev only):")
    print(f"  password: {args.password}")
    for role, email, _ in STAFF:
        print(f"  {role:<9}{email}")
    print("  donors   donor1.demo@example.com ... donor3.demo@example.com")
    print("  people   recipient1.demo@example.com ... recipient8.demo@example.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
