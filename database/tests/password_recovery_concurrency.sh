#!/usr/bin/env bash
# Concurrency checks for patch 002: two REAL database sessions run at the same moment against the same person.
#   usage:  PGHOST=... PGPORT=... PGUSER=postgres bash database/tests/password_recovery_concurrency.sh <scratch-database>
# Session A takes the lock and holds its transaction open for ~2 s; session B starts ~0.7 s later and so overlaps it.
# WARNING: unlike the other test files this one COMMITS rows (it needs two sessions). It creates its own throw-away users, removes
# its recovery codes and users at the end, and leaves only append-only audit rows. Run it on a development/scratch database only.
set -u
DB="${1:?usage: password_recovery_concurrency.sh <scratch-database>}"
case "$DB" in sadqah|sadqah_prod|production|prod) echo "refusing to run on '$DB': use a scratch database"; exit 2;; esac
P=(psql -X -q -At -v ON_ERROR_STOP=1 -d "$DB")
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
FAIL=0
ok()   { echo "  PASS  $1"; }
bad()  { echo "  FAIL  $1"; FAIL=1; }
H()    { echo "decode(md5('$1')||md5('$1x'),'hex')"; }     # a 32-byte stand-in for the code HMAC

TAG="cc$$_$RANDOM"
"${P[@]}" -c "INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,email_verified_at) VALUES
   ('donor','\x01',decode(md5('$TAG-u1'),'hex'),'old-hash',now()),
   ('donor','\x02',decode(md5('$TAG-u2'),'hex'),'old-hash',now()),
   ('admin','\x03',decode(md5('$TAG-a1'),'hex'),'h',now()),
   ('admin','\x04',decode(md5('$TAG-a2'),'hex'),'h',now())"
uid()  { "${P[@]}" -c "SELECT id FROM core.users WHERE email_blind_idx = decode(md5('$TAG-$1'),'hex')"; }
U1=$(uid u1); U2=$(uid u2); A1=$(uid a1); A2=$(uid a2)
B() { echo "decode(md5('$TAG-$1'),'hex')"; }
reset_codes() { "${P[@]}" -c "DELETE FROM core.password_resets WHERE user_id IN ('$U1','$U2')"; }
open_rows()   { "${P[@]}" -c "SELECT count(*) FROM core.password_resets WHERE user_id='$1' AND consumed_at IS NULL AND invalidated_at IS NULL"; }
all_rows()    { "${P[@]}" -c "SELECT count(*) FROM core.password_resets WHERE user_id='$1'"; }

# run <name> <delay> <sql>  : one session in the background, stdout/stderr/exit status kept in $W
run() { ( sleep "$2"; "${P[@]}" -c "$3" >"$W/$1.out" 2>"$W/$1.err"; echo $? >"$W/$1.rc" ) & }
HOLD="SELECT pg_sleep(2);"
rc()  { cat "$W/$1.rc"; }

scenario() { echo "$1"; reset_codes; }

# ---- 1. two self-service requests at once for the same e-mail -------------------------------------------------------------
scenario "1. two simultaneous 'forgot password' requests"
run A 0   "BEGIN; SELECT count(*) FROM api.fn_pr_start($(B u1), $(H a), 900); $HOLD COMMIT;"
run B 0.7 "BEGIN; SELECT count(*) FROM api.fn_pr_start($(B u1), $(H b), 900); COMMIT;"
wait
[ "$(rc A)" = 0 ] && [ "$(rc B)" = 0 ] && ok "neither session raised an error" || { bad "a session failed: $(cat "$W/A.err" "$W/B.err")"; }
[ "$(($(grep -h '^[0-9]' "$W/A.out" "$W/B.out" | paste -sd+)))" = 1 ] && ok "exactly one code was issued (the other got the generic empty answer)" || bad "issued: A=$(cat "$W/A.out") B=$(cat "$W/B.out")"
[ "$(open_rows $U1)" = 1 ] && [ "$(all_rows $U1)" = 1 ] && ok "one row, and it is the one open code" || bad "rows: open=$(open_rows $U1) all=$(all_rows $U1)"

# ---- 2. self-service request racing an administrator-initiated one --------------------------------------------------------
scenario "2. self-service request and admin-initiated reset at once"
run A 0   "BEGIN; SELECT count(*) FROM api.fn_pr_start($(B u2), $(H c), 900); $HOLD COMMIT;"
run B 0.7 "BEGIN; SELECT set_config('app.current_user_id','$A1',true); SELECT outcome FROM core.fn_admin_start_reset('$A1', $(B u2), $(H d), 900); COMMIT;"
wait
[ "$(rc A)" = 0 ] && [ "$(rc B)" = 0 ] && ok "no errors" || bad "a session failed: $(cat "$W/A.err" "$W/B.err")"
grep -q too_soon "$W/B.out" && ok "the admin request was told 'too_soon' (not a database error)" || bad "admin outcome: $(cat "$W/B.out")"
[ "$(open_rows $U2)" = 1 ] && [ "$(all_rows $U2)" = 1 ] && ok "one open code" || bad "rows: open=$(open_rows $U2) all=$(all_rows $U2)"

# ---- 3. two administrators racing for the same person ---------------------------------------------------------------------
scenario "3. two administrators start a reset for the same person at once"
run A 0   "BEGIN; SELECT set_config('app.current_user_id','$A1',true); SELECT outcome FROM core.fn_admin_start_reset('$A1', $(B u1), $(H e), 900); $HOLD COMMIT;"
run B 0.7 "BEGIN; SELECT set_config('app.current_user_id','$A2',true); SELECT outcome FROM core.fn_admin_start_reset('$A2', $(B u1), $(H f), 900); COMMIT;"
wait
[ "$(rc A)" = 0 ] && [ "$(rc B)" = 0 ] && ok "no errors" || bad "a session failed: $(cat "$W/A.err" "$W/B.err")"
grep -q created "$W/A.out" && grep -q too_soon "$W/B.out" && ok "first got 'created', second got 'too_soon'" || bad "outcomes: A=$(cat "$W/A.out") B=$(cat "$W/B.out")"
[ "$(open_rows $U1)" = 1 ] && [ "$(all_rows $U1)" = 1 ] && ok "one open code" || bad "rows: open=$(open_rows $U1) all=$(all_rows $U1)"

# ---- 4. a request racing a normal password change: the change must win (no code survives) --------------------------------
scenario "4. 'forgot password' request while the owner changes their password"
run A 0   "BEGIN; SELECT count(*) FROM api.fn_pr_start($(B u2), $(H g), 900); $HOLD COMMIT;"
run B 0.7 "BEGIN; SELECT set_config('app.current_user_id','$U2',true); SELECT api.fn_set_my_password_hash('changed-hash'); COMMIT;"
wait
[ "$(rc A)" = 0 ] && [ "$(rc B)" = 0 ] && ok "no errors" || bad "a session failed: $(cat "$W/A.err" "$W/B.err")"
[ "$(open_rows $U2)" = 0 ] && ok "no recovery code is left open after the change" || bad "open codes: $(open_rows $U2)"

# ---- 5. redeeming a code while another request is issued: no deadlock, no error -----------------------------------------
scenario "5. redeem while a new code is requested (lock-order / deadlock check)"
"${P[@]}" -c "SELECT count(*) FROM api.fn_pr_start($(B u1), $(H h), 900)" >/dev/null
"${P[@]}" -c "UPDATE core.password_resets SET created_at=created_at-interval '5 minutes' WHERE user_id='$U1'"
run A 0   "BEGIN; SELECT api.fn_pr_redeem($(B u1), $(H h), 'new-hash'); $HOLD COMMIT;"
run B 0.7 "BEGIN; SELECT count(*) FROM api.fn_pr_start($(B u1), $(H i), 900); COMMIT;"
wait
[ "$(rc A)" = 0 ] && [ "$(rc B)" = 0 ] && ok "no errors or deadlock" || bad "a session failed: $(cat "$W/A.err" "$W/B.err")"
grep -q '^t' "$W/A.out" && ok "redeem succeeded" || bad "redeem: $(cat "$W/A.out")"
[ "$(open_rows $U1)" -le 1 ] && ok "at most one open code" || bad "open codes: $(open_rows $U1)"

# ---- clean up what this script created ---------------------------------------------------------------------------------------
reset_codes
"${P[@]}" -c "DELETE FROM core.users WHERE id IN ('$U1','$U2','$A1','$A2')" || echo "  (could not delete the test users; they are inactive-looking throw-away rows: tag $TAG)"
[ "$FAIL" = 0 ] && echo "password_recovery_concurrency: all checks passed" || { echo "password_recovery_concurrency: FAILED"; exit 1; }
