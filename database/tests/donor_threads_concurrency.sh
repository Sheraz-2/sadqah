#!/usr/bin/env bash
# Real-concurrency proof for api.fn_my_post_message (patch 003): independent database connections/transactions send a donor message for the
# SAME paid-out public donation that already holds 9 donor messages from the last 24 hours. Exactly one must succeed, exactly one must be
# refused by the 10-per-24-hours limit, and the final count must be 10.
#
# UNLIKE the other files in database/tests this one COMMITS its fixture rows (two connections cannot see each other's uncommitted data), so run
# it ONLY against a throwaway database built from roles.sql + schema.sql + patches/, then drop that database. It refuses to run otherwise:
#   createdb sadqah_conc   (then apply roles.sql, schema.sql and patches/*.sql to it)
#   ALLOW_THROWAWAY_DB=1 PGDATABASE=sadqah_conc PGUSER=postgres bash database/tests/donor_threads_concurrency.sh
#   dropdb sadqah_conc
# Part 1 is deterministic: connection A sends and keeps its transaction open; connection B is started while A holds it, must be seen WAITING on
# the donation row lock in pg_stat_activity, and must be refused once A commits. Part 2 repeats the race with both connections released at the
# same instant (a pg_sleep_until barrier) over ROUNDS fresh donations.
set -u
[ "${ALLOW_THROWAWAY_DB:-}" = "1" ] || { echo "Refusing to run: this test commits data. Point it at a THROWAWAY database and set ALLOW_THROWAWAY_DB=1."; exit 2; }
PSQL="${PSQL:-psql}"; ROUNDS="${ROUNDS:-12}"
P() { $PSQL -X -q -At "$@"; }
fail() { echo "FAIL: $*"; exit 1; }
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

# ---- fixture (committed): a donor, a recipient with an active campaign, and ROUNDS+1 delivered public donations, each with 9 recent donor messages
P -v ON_ERROR_STOP=1 -v rounds="$ROUNDS" > "$WORK/ids" <<'SQL' || fail "fixture could not be created (is this a database with roles.sql, schema.sql and patches applied?)"
CREATE TEMP TABLE ids(k text, v text);
DO $$
DECLARE d1 uuid; ra uuid; rv uuid; sa uuid; cid uuid;
BEGIN
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,display_name,country_code) VALUES ('donor','\xc001','\xc00101','h','Conc Donor','PK') RETURNING id INTO d1;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,country_code) VALUES ('recipient','\xc002','\xc00202','h','PK') RETURNING id INTO ra;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash) VALUES ('reviewer','\xc003','\xc00303','h') RETURNING id INTO rv;
  INSERT INTO core.recipients (user_id,slug,public_name,region_country,paypal_receiver_type,paypal_receiver_enc,paypal_receiver_blind_idx,story,business_type)
    VALUES (ra,'conc-a','Ana','PK','EMAIL','\x04','\xc00404','story','tailoring') RETURNING id INTO sa;
  INSERT INTO core.recipients_kyc (recipient_id,status,full_name_enc,nic_number_enc,nic_blind_idx,address_enc,doc_country,consent_biometric_at,consent_data_at)
    VALUES (sa,'needs_human_review','\x05','\x06','\xc00601','\x07','PK',now(),now());
  INSERT INTO core.kyc_documents (recipient_id,doc_type,object_key,sha256,mime_type,size_bytes,wrapped_dek)
    VALUES (sa,'national_id',repeat('c',68),sha256('x'),'image/png',10,'\x08');
  UPDATE core.recipients_kyc SET ai_assessed_at=now(), ai_fraud_risk_score=0.1, ai_recommended_allocation_cents=20000 WHERE recipient_id=sa;
  PERFORM core.fn_review_kyc(sa,'approved',3000,20000,rv,NULL);
  UPDATE core.recipients SET profile_public=true, consent_public_profile_at=now() WHERE id=sa;
  INSERT INTO core.campaigns (recipient_id,slug,title,story,goal_cents,status) VALUES (sa,'conc-camp','Conc campaign','story',10000,'active') RETURNING id INTO cid;
  INSERT INTO ids VALUES ('donor', d1::text), ('campaign', cid::text), ('recipient', sa::text);
END $$;
ALTER TABLE core.donations DISABLE TRIGGER USER;   -- ledger/payout side effects are not under test; the MESSAGE trigger stays on
INSERT INTO core.donations (campaign_id,recipient_id,is_anonymous,donor_user_id,amount_cents,status,paypal_capture_id,captured_at,paid_out_at)
  SELECT (SELECT v::uuid FROM ids WHERE k='campaign'), (SELECT v::uuid FROM ids WHERE k='recipient'), false, (SELECT v::uuid FROM ids WHERE k='donor'),
         2500, 'paid_out', 'conc-cap-'||g, now(), now()
    FROM generate_series(0, :rounds) g;
ALTER TABLE core.donations ENABLE TRIGGER USER;
INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status,created_at)
  SELECT d.id, 'donor', decode(repeat('0'||j::text,40),'hex'), 'approved', now() - interval '1 hour'
    FROM core.donations d, generate_series(1,9) j WHERE d.paypal_capture_id LIKE 'conc-cap-%';
INSERT INTO ids SELECT 'd'||lpad(substr(paypal_capture_id,10),3,'0'), id::text FROM core.donations WHERE paypal_capture_id LIKE 'conc-cap-%';
SELECT k||'='||v FROM ids ORDER BY k;
SQL
DONOR=$(grep '^donor=' "$WORK/ids" | cut -d= -f2); [ -n "$DONOR" ] || fail "no donor id in fixture output"
mapfile -t DONS < <(grep '^d[0-9]' "$WORK/ids" | cut -d= -f2)
[ "${#DONS[@]}" -eq $((ROUNDS+1)) ] || fail "expected $((ROUNDS+1)) donations, got ${#DONS[@]}"
count_msgs() { P -c "SELECT count(*) FROM core.anonymous_messages WHERE donation_id='$1' AND sender='donor' AND created_at > now() - interval '24 hours'"; }
for d in "${DONS[@]}"; do [ "$(count_msgs "$d")" = "9" ] || fail "fixture: donation $d must start with exactly 9 donor messages"; done

# a call as the signed-in donor through the web login (sadqah_api), exactly as the API does
as_donor() { printf "SET ROLE sadqah_api;\nSELECT set_config('app.current_user_id','%s',false);\n" "$DONOR"; }

# ---------------------------------------------------------------- Part 1: deterministic overlap on DONS[0]
D="${DONS[0]}"
{ as_donor; cat <<SQL
BEGIN;
SELECT 'OK:' || api.fn_my_post_message('$D', decode(repeat('aa',40),'hex'));
SELECT pg_sleep(3);
COMMIT;
SQL
} | $PSQL -X -q -At > "$WORK/a.out" 2> "$WORK/a.err" &
PID_A=$!
sleep 1
T0=$(date +%s%N)
{ as_donor; echo "SELECT 'OK:' || api.fn_my_post_message('$D', decode(repeat('bb',40),'hex'));"; } | $PSQL -X -q -At > "$WORK/b.out" 2> "$WORK/b.err" &
PID_B=$!
sleep 1
WAITING=$(P -c "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND query LIKE '%fn_my_post_message%' AND pid <> pg_backend_pid()")
wait $PID_A; wait $PID_B
T1=$(date +%s%N); B_MS=$(( (T1 - T0) / 1000000 ))
[ "$WAITING" = "1" ] || fail "part 1: connection B was not waiting on a lock while A held the donation row (waiting=$WAITING)"
[ "$B_MS" -ge 1500 ] || fail "part 1: connection B returned after only ${B_MS} ms, it did not wait for A's transaction"
grep -q '^OK:' "$WORK/a.out" || fail "part 1: connection A (first in) should have succeeded: $(cat "$WORK/a.err")"
! grep -q '^OK:' "$WORK/b.out" || fail "part 1: connection B must NOT have succeeded (limit exceeded)"
grep -q 'message limit reached for today' "$WORK/b.err" || fail "part 1: connection B should have been refused by the rate limit: $(cat "$WORK/b.err")"
[ "$(count_msgs "$D")" = "10" ] || fail "part 1: final count is $(count_msgs "$D"), expected exactly 10"
echo "part 1 ok: B waited on the row lock (${B_MS} ms), then was refused; final count 10"

# ---------------------------------------------------------------- Part 2: simultaneous release, fresh donation per round
OKS=0
for ((r=1; r<=ROUNDS; r++)); do
  D="${DONS[$r]}"; T=$(( $(date +%s) + 1 ))
  for who in x y; do
    { as_donor; cat <<SQL
SELECT pg_sleep_until(to_timestamp($T));
SELECT 'OK:' || api.fn_my_post_message('$D', decode(repeat('cc',40),'hex'));
SQL
    } | $PSQL -X -q -At > "$WORK/$who.out" 2> "$WORK/$who.err" &
  done
  wait
  n_ok=$(cat "$WORK/x.out" "$WORK/y.out" | grep -c '^OK:')
  n_lim=$(cat "$WORK/x.err" "$WORK/y.err" | grep -c 'message limit reached for today')
  [ "$n_ok" = "1" ] && [ "$n_lim" = "1" ] || fail "part 2 round $r: successes=$n_ok limit-refusals=$n_lim (expected 1 and 1): $(cat "$WORK/x.err" "$WORK/y.err")"
  [ "$(count_msgs "$D")" = "10" ] || fail "part 2 round $r: final count is $(count_msgs "$D"), expected exactly 10"
  OKS=$((OKS+1))
done
echo "part 2 ok: $OKS simultaneous rounds, each exactly 1 success + 1 refusal, final count 10"
echo "donor_threads_concurrency: all assertions passed"
