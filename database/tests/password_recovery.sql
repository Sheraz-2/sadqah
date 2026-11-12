-- Assertions for patch 002 (password recovery). One transaction, rolled back.
-- psql -h ... -U postgres -d sadqah -v ON_ERROR_STOP=1 -f database/tests/password_recovery.sql
BEGIN;
CREATE TEMP TABLE t(k text PRIMARY KEY, v text);
GRANT ALL ON t TO PUBLIC;

-- people: donor (unverified e-mail), recipient (verified e-mail), second donor with a verified phone, reviewer, two admins
DO $$
DECLARE d uuid; r uuid; p uuid; v uuid; a uuid; a2 uuid;
BEGIN
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash) VALUES ('donor','\x01','\xd001','old-hash') RETURNING id INTO d;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,email_verified_at,failed_login_count,locked_until)
    VALUES ('recipient','\x02','\xd002','old-hash',now(),5,now()+interval '15 minutes') RETURNING id INTO r;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,phone_enc,phone_blind_idx,phone_verified_at)
    VALUES ('donor','\x03','\xd003','old-hash','\x0a','\x0a0a',now()) RETURNING id INTO p;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,email_verified_at) VALUES ('reviewer','\x04','\xd004','h',now()) RETURNING id INTO v;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,email_verified_at) VALUES ('admin','\x05','\xd005','h',now()) RETURNING id INTO a;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,email_verified_at) VALUES ('admin','\x06','\xd006','h',now()) RETURNING id INTO a2;
  INSERT INTO t VALUES ('d',d::text),('r',r::text),('p',p::text),('v',v::text),('a',a::text),('a2',a2::text);
END $$;

-- helper: a 32-byte "HMAC" for code n
CREATE FUNCTION pg_temp.h(n int) RETURNS bytea LANGUAGE sql IMMUTABLE AS $$ SELECT sha256(('code-' || n)::text::bytea) $$;
-- helper: make the newest reset for a user look old enough to pass the cooldown
CREATE FUNCTION pg_temp.age(u text) RETURNS void LANGUAGE sql AS $$
  UPDATE core.password_resets SET created_at = created_at - interval '5 minutes', expires_at = expires_at - interval '5 minutes' WHERE user_id = u::uuid $$;
GRANT EXECUTE ON FUNCTION pg_temp.h(int) TO PUBLIC;
-- helper: act as a signed-in user, the way the web tier does (it sets app.current_user_id for the transaction)
CREATE FUNCTION pg_temp.as_user(u text) RETURNS void LANGUAGE sql AS $$ SELECT set_config('app.current_user_id', u, true) $$;

-- ---- start: unknown e-mail gives nothing; known gives one row; cooldown; bad params
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM api.fn_pr_start('\xffff', pg_temp.h(1), 900); IF n<>0 THEN RAISE EXCEPTION 'unknown e-mail returned a row'; END IF;
  SELECT count(*) INTO n FROM api.fn_pr_start('\xd001', pg_temp.h(1), 900); IF n<>1 THEN RAISE EXCEPTION 'known e-mail should issue a code'; END IF;
  SELECT count(*) INTO n FROM api.fn_pr_start('\xd001', pg_temp.h(2), 900); IF n<>0 THEN RAISE EXCEPTION 'cooldown not enforced'; END IF;
  BEGIN PERFORM api.fn_pr_start('\xd001', 'short'::bytea, 900); RAISE EXCEPTION 'bad hmac accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  BEGIN PERFORM api.fn_pr_start('\xd001', pg_temp.h(1), 5); RAISE EXCEPTION 'ttl 5s accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  BEGIN PERFORM api.fn_pr_start('\xd001', pg_temp.h(1), 900, 'carrier-pigeon'); RAISE EXCEPTION 'bad channel accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  SELECT count(*) INTO n FROM api.fn_pr_start('\xd003', pg_temp.h(9), 900, 'sms'); IF n<>1 THEN RAISE EXCEPTION 'verified phone should allow sms issue'; END IF;
  SELECT count(*) INTO n FROM api.fn_pr_start('\xd001', pg_temp.h(1), 900, 'sms'); IF n<>0 THEN RAISE EXCEPTION 'sms must not issue without a verified phone'; END IF;
END $$;

-- ---- the stored value is only the HMAC, never the code; the audit log carries no secrets
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM core.audit_log WHERE action LIKE 'password_reset.%' AND (details::text ~* 'code|hmac|otp' )) THEN RAISE EXCEPTION 'audit details mention a code'; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.audit_log WHERE action='password_reset.requested' AND actor_user_id=(SELECT v FROM t WHERE k='d')::uuid) THEN RAISE EXCEPTION 'request not audited'; END IF;
END $$;

-- ---- redeem: wrong code costs an attempt, right code works exactly once
DO $$ DECLARE ok boolean; a int; BEGIN
  ok := api.fn_pr_redeem('\xd001', pg_temp.h(99), 'new-hash'); IF ok THEN RAISE EXCEPTION 'wrong code accepted'; END IF;
  SELECT attempts INTO a FROM core.password_resets WHERE user_id=(SELECT v FROM t WHERE k='d')::uuid AND invalidated_at IS NULL AND consumed_at IS NULL;
  IF a<>1 THEN RAISE EXCEPTION 'attempt not counted (%)', a; END IF;
  ok := api.fn_pr_redeem('\xffff', pg_temp.h(1), 'new-hash'); IF ok THEN RAISE EXCEPTION 'unknown e-mail redeemed'; END IF;
  ok := api.fn_pr_redeem('\xd001', pg_temp.h(1), ''); IF ok THEN RAISE EXCEPTION 'empty hash accepted'; END IF;
  ok := api.fn_pr_redeem('\xd001', pg_temp.h(1), 'new-hash'); IF NOT ok THEN RAISE EXCEPTION 'right code refused'; END IF;
  IF (SELECT password_hash FROM core.users WHERE id=(SELECT v FROM t WHERE k='d')::uuid) <> 'new-hash' THEN RAISE EXCEPTION 'password not changed'; END IF;
  IF (SELECT email_verified_at FROM core.users WHERE id=(SELECT v FROM t WHERE k='d')::uuid) IS NULL THEN RAISE EXCEPTION 'inbox control not recorded'; END IF;
  ok := api.fn_pr_redeem('\xd001', pg_temp.h(1), 'again-hash'); IF ok THEN RAISE EXCEPTION 'a code worked twice'; END IF;
  IF (SELECT password_hash FROM core.users WHERE id=(SELECT v FROM t WHERE k='d')::uuid) <> 'new-hash' THEN RAISE EXCEPTION 'password changed by a replay'; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.audit_log WHERE action='password_reset.completed' AND actor_user_id=(SELECT v FROM t WHERE k='d')::uuid) THEN RAISE EXCEPTION 'completion not audited'; END IF;
END $$;

-- ---- attempt limit: five wrong guesses kill the code, even if the sixth is right
SELECT pg_temp.age((SELECT v FROM t WHERE k='r'));
DO $$ DECLARE ok boolean; i int; BEGIN
  PERFORM api.fn_pr_start('\xd002', pg_temp.h(10), 900);
  FOR i IN 1..5 LOOP ok := api.fn_pr_redeem('\xd002', pg_temp.h(100+i), 'x'); IF ok THEN RAISE EXCEPTION 'guess accepted'; END IF; END LOOP;
  ok := api.fn_pr_redeem('\xd002', pg_temp.h(10), 'locked-out-hash'); IF ok THEN RAISE EXCEPTION 'code worked after lockout'; END IF;
  IF (SELECT password_hash FROM core.users WHERE id=(SELECT v FROM t WHERE k='r')::uuid) <> 'old-hash' THEN RAISE EXCEPTION 'locked-out code changed the password'; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.audit_log WHERE action='password_reset.locked_out') THEN RAISE EXCEPTION 'lockout not audited'; END IF;
END $$;

-- ---- a new code after lockout works, and unlocks a locked account (the point of recovery)
SELECT pg_temp.age((SELECT v FROM t WHERE k='r'));
DO $$ DECLARE ok boolean; BEGIN
  IF (SELECT locked_until FROM core.users WHERE id=(SELECT v FROM t WHERE k='r')::uuid) IS NULL THEN RAISE EXCEPTION 'fixture: should start locked'; END IF;
  PERFORM api.fn_pr_start('\xd002', pg_temp.h(11), 900);
  ok := api.fn_pr_redeem('\xd002', pg_temp.h(11), 'fresh-hash'); IF NOT ok THEN RAISE EXCEPTION 'fresh code refused'; END IF;
  IF (SELECT failed_login_count FROM core.users WHERE id=(SELECT v FROM t WHERE k='r')::uuid)<>0
     OR (SELECT locked_until FROM core.users WHERE id=(SELECT v FROM t WHERE k='r')::uuid) IS NOT NULL THEN RAISE EXCEPTION 'account not unlocked'; END IF;
END $$;

-- ---- expiry: an expired code is refused (and closed)
SELECT pg_temp.age((SELECT v FROM t WHERE k='r'));
DO $$ DECLARE ok boolean; BEGIN
  PERFORM api.fn_pr_start('\xd002', pg_temp.h(12), 60);
  UPDATE core.password_resets SET created_at = now() - interval '2 hours', expires_at = now() - interval '1 hour'
   WHERE user_id=(SELECT v FROM t WHERE k='r')::uuid AND consumed_at IS NULL AND invalidated_at IS NULL;
  ok := api.fn_pr_redeem('\xd002', pg_temp.h(12), 'late-hash'); IF ok THEN RAISE EXCEPTION 'expired code accepted'; END IF;
  IF (SELECT password_hash FROM core.users WHERE id=(SELECT v FROM t WHERE k='r')::uuid) = 'late-hash' THEN RAISE EXCEPTION 'expired code changed password'; END IF;
  IF EXISTS (SELECT 1 FROM core.password_resets WHERE user_id=(SELECT v FROM t WHERE k='r')::uuid AND consumed_at IS NULL AND invalidated_at IS NULL) THEN RAISE EXCEPTION 'expired code left open'; END IF;
END $$;

-- ---- a newer code replaces the older one
SELECT pg_temp.age((SELECT v FROM t WHERE k='r'));
DO $$ DECLARE ok boolean; BEGIN
  PERFORM api.fn_pr_start('\xd002', pg_temp.h(20), 900);
  PERFORM pg_temp.age((SELECT v FROM t WHERE k='r'));
  UPDATE core.password_resets SET expires_at = now() + interval '10 minutes' WHERE user_id=(SELECT v FROM t WHERE k='r')::uuid AND invalidated_at IS NULL AND consumed_at IS NULL;
  PERFORM api.fn_pr_start('\xd002', pg_temp.h(21), 900);
  ok := api.fn_pr_redeem('\xd002', pg_temp.h(20), 'stale'); IF ok THEN RAISE EXCEPTION 'replaced code still worked'; END IF;
  ok := api.fn_pr_redeem('\xd002', pg_temp.h(21), 'newest'); IF NOT ok THEN RAISE EXCEPTION 'newest code refused'; END IF;
END $$;

-- ---- hourly cap holds in the database too
DO $$ DECLARE n int; i int; BEGIN
  FOR i IN 1..5 LOOP
    PERFORM pg_temp.age((SELECT v FROM t WHERE k='p'));
    PERFORM api.fn_pr_start('\xd003', pg_temp.h(30+i), 900);
  END LOOP;
  -- ageing shifted created_at by 5 minutes each time, so all are still within the hour; the next one must be refused
  PERFORM pg_temp.age((SELECT v FROM t WHERE k='p'));
  SELECT count(*) INTO n FROM api.fn_pr_start('\xd003', pg_temp.h(40), 900);
  IF n<>0 THEN RAISE EXCEPTION 'hourly cap not enforced'; END IF;
END $$;

-- ---- delivery failure closes the code
SELECT pg_temp.age((SELECT v FROM t WHERE k='d'));
DO $$ DECLARE rid uuid; ok boolean; BEGIN
  SELECT reset_id INTO rid FROM api.fn_pr_start('\xd001', pg_temp.h(50), 900);
  PERFORM api.fn_pr_delivery_failed(rid, 'SMTPException');
  ok := api.fn_pr_redeem('\xd001', pg_temp.h(50), 'x'); IF ok THEN RAISE EXCEPTION 'undelivered code still works'; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.audit_log WHERE action='password_reset.delivery_failed') THEN RAISE EXCEPTION 'delivery failure not audited'; END IF;
END $$;

-- ---- admin-initiated: only an admin; verified e-mail only; not admins; not yourself; audited
DO $$ DECLARE o record; adm uuid := (SELECT v FROM t WHERE k='a')::uuid; BEGIN
  -- reviewer and ordinary users are refused (each one signed in as themselves, so the identity check passes and the ROLE check is what refuses)
  PERFORM pg_temp.as_user((SELECT v FROM t WHERE k='v'));
  BEGIN PERFORM core.fn_admin_start_reset((SELECT v FROM t WHERE k='v')::uuid,'\xd002',pg_temp.h(60),900); RAISE EXCEPTION 'reviewer allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  PERFORM pg_temp.as_user((SELECT v FROM t WHERE k='r'));
  BEGIN PERFORM core.fn_admin_start_reset((SELECT v FROM t WHERE k='r')::uuid,'\xd002',pg_temp.h(60),900); RAISE EXCEPTION 'recipient allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  PERFORM pg_temp.as_user(gen_random_uuid()::text);
  BEGIN PERFORM core.fn_admin_start_reset(current_setting('app.current_user_id')::uuid,'\xd002',pg_temp.h(60),900); RAISE EXCEPTION 'unknown actor allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  PERFORM pg_temp.as_user(adm::text);
  UPDATE core.users SET is_active=false WHERE id=adm; -- a deactivated admin is refused too
  BEGIN PERFORM core.fn_admin_start_reset(adm,'\xd002',pg_temp.h(60),900); RAISE EXCEPTION 'inactive admin allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  UPDATE core.users SET is_active=true WHERE id=adm;
  -- the named administrator must be the signed-in user (a real admin id alone is not enough)
  PERFORM pg_temp.as_user((SELECT v FROM t WHERE k='a2'));
  BEGIN PERFORM core.fn_admin_start_reset(adm,'\xd002',pg_temp.h(60),900); RAISE EXCEPTION 'another admin id accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  PERFORM pg_temp.as_user((SELECT v FROM t WHERE k='r'));   -- an ordinary user naming an admin
  BEGIN PERFORM core.fn_admin_start_reset(adm,'\xd002',pg_temp.h(60),900); RAISE EXCEPTION 'admin id accepted from a non-admin session';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  PERFORM pg_temp.as_user('');                               -- no signed-in user at all
  BEGIN PERFORM core.fn_admin_start_reset(adm,'\xd002',pg_temp.h(60),900); RAISE EXCEPTION 'accepted with no session user';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN PERFORM core.fn_admin_start_reset(NULL,'\xd002',pg_temp.h(60),900); RAISE EXCEPTION 'NULL admin accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  IF EXISTS (SELECT 1 FROM core.password_resets WHERE user_id=(SELECT v FROM t WHERE k='r')::uuid AND initiated_by IS NOT NULL) THEN RAISE EXCEPTION 'a refused call left a code behind'; END IF;
  PERFORM pg_temp.as_user(adm::text);
  -- targets that are not eligible
  SELECT * INTO o FROM core.fn_admin_start_reset(adm,'\xffff',pg_temp.h(61),900); IF o.outcome<>'no_eligible_account' OR o.email_ct IS NOT NULL THEN RAISE EXCEPTION 'unknown target: %', o.outcome; END IF;
  UPDATE core.users SET email_verified_at=NULL WHERE id=(SELECT v FROM t WHERE k='d')::uuid;
  SELECT * INTO o FROM core.fn_admin_start_reset(adm,'\xd001',pg_temp.h(61),900); IF o.outcome<>'no_eligible_account' OR o.email_ct IS NOT NULL THEN RAISE EXCEPTION 'unverified target: %', o.outcome; END IF;
  SELECT * INTO o FROM core.fn_admin_start_reset(adm,'\xd006',pg_temp.h(61),900); IF o.outcome<>'no_eligible_account' THEN RAISE EXCEPTION 'admin target: %', o.outcome; END IF;
  SELECT * INTO o FROM core.fn_admin_start_reset(adm,'\xd005',pg_temp.h(61),900); IF o.outcome<>'no_eligible_account' THEN RAISE EXCEPTION 'self target: %', o.outcome; END IF;
  UPDATE core.users SET is_active=false WHERE id=(SELECT v FROM t WHERE k='r')::uuid;
  SELECT * INTO o FROM core.fn_admin_start_reset(adm,'\xd002',pg_temp.h(61),900); IF o.outcome<>'no_eligible_account' THEN RAISE EXCEPTION 'inactive target: %', o.outcome; END IF;
  UPDATE core.users SET is_active=true WHERE id=(SELECT v FROM t WHERE k='r')::uuid;
END $$;
SELECT pg_temp.age((SELECT v FROM t WHERE k='r'));
SELECT pg_temp.as_user((SELECT v FROM t WHERE k='a'));
DO $$ DECLARE o record; adm uuid := (SELECT v FROM t WHERE k='a')::uuid; ok boolean; BEGIN
  SELECT * INTO o FROM core.fn_admin_start_reset(adm,'\xd002',pg_temp.h(70),900);
  IF o.outcome<>'created' OR o.reset_id IS NULL OR o.email_ct IS NULL THEN RAISE EXCEPTION 'eligible target not created: %', o.outcome; END IF;
  IF (SELECT initiated_by FROM core.password_resets WHERE id=o.reset_id) <> adm THEN RAISE EXCEPTION 'initiator not recorded'; END IF;
  SELECT * INTO o FROM core.fn_admin_start_reset(adm,'\xd002',pg_temp.h(71),900); IF o.outcome<>'too_soon' THEN RAISE EXCEPTION 'cooldown not enforced for admin: %', o.outcome; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.audit_log WHERE action='password_reset.admin_initiated' AND actor_user_id=adm AND entity_id=(SELECT v FROM t WHERE k='r')) THEN RAISE EXCEPTION 'admin start not audited'; END IF;
  IF EXISTS (SELECT 1 FROM core.audit_log WHERE action LIKE 'password_reset.admin%' AND details::text ~* 'code|hmac|password|otp|@') THEN RAISE EXCEPTION 'secret-looking text in audit'; END IF;
  -- the admin's code is redeemed through the normal path, by the user, with the e-mailed code
  ok := api.fn_pr_redeem('\xd002', pg_temp.h(70), 'by-user'); IF NOT ok THEN RAISE EXCEPTION 'user could not redeem admin-initiated code'; END IF;
END $$;

-- ---- a normal password change closes any recovery code still open (api.fn_set_my_password_hash)
SELECT pg_temp.age((SELECT v FROM t WHERE k='p'));
DO $$ DECLARE n int; ok boolean; p uuid := (SELECT v FROM t WHERE k='p')::uuid; BEGIN
  -- the hourly cap from the earlier test still applies to this person, so use a fresh one for the issue step
  UPDATE core.password_resets SET created_at = created_at - interval '2 hours', expires_at = expires_at - interval '2 hours' WHERE user_id = p;
  SELECT count(*) INTO n FROM api.fn_pr_start('\xd003', pg_temp.h(80), 900); IF n<>1 THEN RAISE EXCEPTION 'fixture: code not issued'; END IF;
  -- not signed in: refused, and the code is untouched
  PERFORM pg_temp.as_user('');
  BEGIN PERFORM api.fn_set_my_password_hash('anon-hash'); RAISE EXCEPTION 'anonymous password change allowed'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  IF NOT EXISTS (SELECT 1 FROM core.password_resets WHERE user_id=p AND consumed_at IS NULL AND invalidated_at IS NULL) THEN RAISE EXCEPTION 'code closed by a refused call'; END IF;
  -- signed in: password changes, lock state clears, the outstanding code is closed
  UPDATE core.users SET failed_login_count = 3 WHERE id = p;
  PERFORM pg_temp.as_user(p::text);
  PERFORM api.fn_set_my_password_hash('self-changed-hash');
  IF (SELECT password_hash FROM core.users WHERE id=p) <> 'self-changed-hash' THEN RAISE EXCEPTION 'password not changed'; END IF;
  IF (SELECT failed_login_count FROM core.users WHERE id=p) <> 0 THEN RAISE EXCEPTION 'failed logins not cleared'; END IF;
  IF EXISTS (SELECT 1 FROM core.password_resets WHERE user_id=p AND consumed_at IS NULL AND invalidated_at IS NULL) THEN RAISE EXCEPTION 'recovery code survived a password change'; END IF;
  ok := api.fn_pr_redeem('\xd003', pg_temp.h(80), 'attacker-hash'); IF ok THEN RAISE EXCEPTION 'old recovery code worked after a password change'; END IF;
  IF (SELECT password_hash FROM core.users WHERE id=p) <> 'self-changed-hash' THEN RAISE EXCEPTION 'password overwritten by a dead code'; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.audit_log WHERE action='account.password_changed' AND actor_user_id=p AND (details->>'recovery_codes_closed')::int = 1) THEN RAISE EXCEPTION 'change/closure not audited'; END IF;
  -- with nothing outstanding the behaviour is the plain one (audited, no count)
  PERFORM api.fn_set_my_password_hash('second-hash');
  IF (SELECT password_hash FROM core.users WHERE id=p) <> 'second-hash' THEN RAISE EXCEPTION 'second change failed'; END IF;
  -- the account can still recover afterwards (cooldown aside): a new code is issued normally
  PERFORM pg_temp.age(p::text);
  SELECT count(*) INTO n FROM api.fn_pr_start('\xd003', pg_temp.h(81), 900); IF n <> 1 THEN RAISE EXCEPTION 'cannot request a new code after a change'; END IF;
  -- a password change by one person does not close another person's code
  UPDATE core.password_resets SET created_at = created_at - interval '2 hours', expires_at = expires_at - interval '2 hours' WHERE user_id = (SELECT v FROM t WHERE k='r')::uuid;
  SELECT count(*) INTO n FROM api.fn_pr_start('\xd002', pg_temp.h(82), 900); IF n<>1 THEN RAISE EXCEPTION 'fixture: second person code not issued'; END IF;
  PERFORM pg_temp.as_user(p::text);
  PERFORM api.fn_set_my_password_hash('third-hash');
  IF NOT EXISTS (SELECT 1 FROM core.password_resets WHERE user_id=(SELECT v FROM t WHERE k='r')::uuid AND consumed_at IS NULL AND invalidated_at IS NULL) THEN RAISE EXCEPTION 'someone else''s code was closed'; END IF;
END $$;

-- ---- the one-open-code rule is a database guarantee, not just a convention
DO $$ BEGIN
  BEGIN
    INSERT INTO core.password_resets (user_id, code_hmac, expires_at)
    SELECT user_id, pg_temp.h(90), now() + interval '5 minutes' FROM core.password_resets
     WHERE consumed_at IS NULL AND invalidated_at IS NULL LIMIT 1;
    RAISE EXCEPTION 'two open codes for one person were accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
END $$;

-- ---- database roles: the web tier's roles can only call their own functions and can never read the table
DO $$ BEGIN
  IF has_table_privilege('sadqah_api','core.password_resets','SELECT') OR has_table_privilege('sadqah_admin','core.password_resets','SELECT')
     OR has_table_privilege('sadqah_worker','core.password_resets','SELECT') THEN RAISE EXCEPTION 'table readable by a service role'; END IF;
  IF NOT has_function_privilege('sadqah_api','api.fn_pr_start(bytea,bytea,integer,text)','EXECUTE')
     OR NOT has_function_privilege('sadqah_api','api.fn_pr_redeem(bytea,bytea,text)','EXECUTE') THEN RAISE EXCEPTION 'api role missing grants'; END IF;
  IF has_function_privilege('sadqah_api','core.fn_admin_start_reset(uuid,bytea,bytea,integer)','EXECUTE') THEN RAISE EXCEPTION 'api role may start admin resets'; END IF;
  IF NOT has_function_privilege('sadqah_admin','core.fn_admin_start_reset(uuid,bytea,bytea,integer)','EXECUTE') THEN RAISE EXCEPTION 'admin role missing grant'; END IF;
  IF NOT has_function_privilege('sadqah_api','api.fn_set_my_password_hash(text)','EXECUTE') THEN RAISE EXCEPTION 'api role lost the password-change grant'; END IF;
  IF has_function_privilege('sadqah_webhook','api.fn_set_my_password_hash(text)','EXECUTE') THEN RAISE EXCEPTION 'password change grant too wide'; END IF;
  IF has_function_privilege('sadqah_admin','api.fn_pr_redeem(bytea,bytea,text)','EXECUTE') OR has_function_privilege('sadqah_worker','api.fn_pr_redeem(bytea,bytea,text)','EXECUTE')
     OR has_function_privilege('sadqah_webhook','core.fn_admin_start_reset(uuid,bytea,bytea,integer)','EXECUTE') THEN RAISE EXCEPTION 'grant too wide'; END IF;
END $$;

ROLLBACK;
\echo 'password_recovery: all assertions passed'
