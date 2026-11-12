-- Assertions for patch 003 (signed-in donor message threads). One transaction, rolled back: leaves no data.
-- Needs a database built from roles.sql + schema.sql + patches/ (001-003). Run as a superuser:
--   psql -X -v ON_ERROR_STOP=1 -d sadqah -f database/tests/donor_threads.sql
-- The functions are exercised as the web login (sadqah_api) with the per-request user set, exactly as the API does.
\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE t(k text PRIMARY KEY, v text);
GRANT ALL ON t TO PUBLIC;

-- ---- fixtures (as superuser): two public donors, one recipient with one active campaign, one reviewer ----------------------
DO $$
DECLARE d1 uuid; d2 uuid; ra uuid; rv uuid; sa uuid; cid uuid;
        dpaid uuid; dcap uuid; dinit uuid; dfail uuid; dbpaid uuid; danon uuid; mid uuid;
BEGIN
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,display_name,country_code) VALUES ('donor','\x01','\x0101','h','Ayesha','PK') RETURNING id INTO d1;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,display_name,country_code) VALUES ('donor','\x11','\x1101','h','Bilal','PK') RETURNING id INTO d2;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,country_code) VALUES ('recipient','\x02','\x0202','h','PK') RETURNING id INTO ra;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash) VALUES ('reviewer','\x03','\x0303','h') RETURNING id INTO rv;
  INSERT INTO core.recipients (user_id,slug,public_name,region_country,paypal_receiver_type,paypal_receiver_enc,paypal_receiver_blind_idx,story,business_type)
    VALUES (ra,'dt-a','Ana','PK','EMAIL','\x04','\x0404','story','tailoring') RETURNING id INTO sa;
  INSERT INTO core.recipients_kyc (recipient_id,status,full_name_enc,nic_number_enc,nic_blind_idx,address_enc,doc_country,consent_biometric_at,consent_data_at)
    VALUES (sa,'needs_human_review','\x05','\x06','\x0601','\x07','PK',now(),now());
  INSERT INTO core.kyc_documents (recipient_id,doc_type,object_key,sha256,mime_type,size_bytes,wrapped_dek)
    VALUES (sa,'national_id',repeat('a',68),sha256('x'),'image/png',10,'\x08');
  UPDATE core.recipients_kyc SET ai_assessed_at=now(), ai_fraud_risk_score=0.1, ai_recommended_allocation_cents=20000 WHERE recipient_id=sa;
  PERFORM core.fn_review_kyc(sa,'approved',3000,20000,rv,NULL);
  UPDATE core.recipients SET profile_public=true, consent_public_profile_at=now() WHERE id=sa;
  INSERT INTO core.campaigns (recipient_id,slug,title,story,goal_cents,status) VALUES (sa,'dt-camp','Ana sewing machine','story',10000,'active') RETURNING id INTO cid;

  -- donations are inserted directly with the donation triggers off (ledger/payout side effects are not under test); the MESSAGE trigger stays on
  ALTER TABLE core.donations DISABLE TRIGGER USER;
  INSERT INTO core.donations (campaign_id,recipient_id,is_anonymous,donor_user_id,amount_cents,status,paypal_capture_id,captured_at,paid_out_at)
    VALUES (cid,sa,false,d1,2500,'paid_out','cap-paid',now(),now()) RETURNING id INTO dpaid;
  INSERT INTO core.donations (campaign_id,recipient_id,is_anonymous,donor_user_id,amount_cents,status,paypal_capture_id,captured_at)
    VALUES (cid,sa,false,d1,1000,'captured','cap-cap',now()) RETURNING id INTO dcap;
  INSERT INTO core.donations (campaign_id,recipient_id,is_anonymous,donor_user_id,amount_cents,status) VALUES (cid,sa,false,d1,1000,'initiated') RETURNING id INTO dinit;
  INSERT INTO core.donations (campaign_id,recipient_id,is_anonymous,donor_user_id,amount_cents,status) VALUES (cid,sa,false,d1,1000,'failed') RETURNING id INTO dfail;
  INSERT INTO core.donations (campaign_id,recipient_id,is_anonymous,donor_user_id,amount_cents,status,paypal_capture_id,captured_at,paid_out_at)
    VALUES (cid,sa,false,d2,5000,'paid_out','cap-b',now(),now()) RETURNING id INTO dbpaid;
  INSERT INTO core.donations (campaign_id,recipient_id,is_anonymous,tracking_token_hash,amount_cents,status,paypal_capture_id,captured_at,paid_out_at)
    VALUES (cid,sa,true,decode(repeat('ab',32),'hex'),3000,'paid_out','cap-anon',now(),now()) RETURNING id INTO danon;
  ALTER TABLE core.donations ENABLE TRIGGER USER;

  -- thread on the donor-1 delivered gift: three donor messages (approved, pending, rejected), three recipient messages (approved, pending, rejected)
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (dpaid,'donor',decode(repeat('01',40),'hex'),'approved') RETURNING id INTO mid; INSERT INTO t VALUES ('m1',mid::text);
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (dpaid,'donor',decode(repeat('02',40),'hex'),'pending') RETURNING id INTO mid; INSERT INTO t VALUES ('m2',mid::text);
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (dpaid,'donor',decode(repeat('03',40),'hex'),'rejected') RETURNING id INTO mid; INSERT INTO t VALUES ('m3',mid::text);
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (dpaid,'recipient',decode(repeat('04',40),'hex'),'approved') RETURNING id INTO mid; INSERT INTO t VALUES ('m4',mid::text);
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (dpaid,'recipient',decode(repeat('05',40),'hex'),'pending') RETURNING id INTO mid; INSERT INTO t VALUES ('m5',mid::text);
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (dpaid,'recipient',decode(repeat('06',40),'hex'),'rejected') RETURNING id INTO mid; INSERT INTO t VALUES ('m6',mid::text);
  -- another donor's thread and the anonymous gift's thread
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (dbpaid,'donor',decode(repeat('07',40),'hex'),'approved');
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (dbpaid,'recipient',decode(repeat('08',40),'hex'),'approved') RETURNING id INTO mid; INSERT INTO t VALUES ('b2',mid::text);
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (danon,'donor',decode(repeat('09',40),'hex'),'approved');
  INSERT INTO core.anonymous_messages (donation_id,sender,body_enc,moderation_status) VALUES (danon,'recipient',decode(repeat('0a',40),'hex'),'approved');

  INSERT INTO t VALUES ('d1',d1::text),('d2',d2::text),('ra',ra::text),('rv',rv::text),
    ('dpaid',dpaid::text),('dcap',dcap::text),('dinit',dinit::text),('dfail',dfail::text),('dbpaid',dbpaid::text),('danon',danon::text);
END $$;

-- the privileges are what the patch grants, nothing more
DO $$ BEGIN
  IF NOT has_function_privilege('sadqah_api','api.fn_my_threads()','EXECUTE') OR NOT has_function_privilege('sadqah_api','api.fn_my_thread_messages(uuid)','EXECUTE')
     OR NOT has_function_privilege('sadqah_api','api.fn_my_post_message(uuid,bytea)','EXECUTE') OR NOT has_function_privilege('sadqah_api','api.fn_my_mark_read(uuid)','EXECUTE')
  THEN RAISE EXCEPTION 'sadqah_api must be able to execute the four donor thread functions'; END IF;
  IF has_function_privilege('sadqah_worker','api.fn_my_threads()','EXECUTE') OR has_function_privilege('sadqah_webhook','api.fn_my_post_message(uuid,bytea)','EXECUTE')
  THEN RAISE EXCEPTION 'other service roles must not be able to execute the donor thread functions'; END IF;
  IF has_table_privilege('sadqah_api','core.anonymous_messages','SELECT') OR has_table_privilege('sadqah_api','core.anonymous_messages','INSERT')
  THEN RAISE EXCEPTION 'sadqah_api must have no direct access to core.anonymous_messages'; END IF;
END $$;

SET LOCAL ROLE sadqah_api;

-- ===== donor 1 =====================================================================================================================
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d1'),true);
DO $$ DECLARE ids uuid[]; is_open boolean; unread bigint; nm text; BEGIN
  -- list: captured and delivered public gifts only (not initiated/failed, not donor 2's, not the anonymous gift)
  SELECT array_agg(donation_id ORDER BY donation_id) INTO ids FROM api.fn_my_threads();
  IF ids IS DISTINCT FROM (SELECT array_agg(v::uuid ORDER BY v::uuid) FROM t WHERE k IN ('dpaid','dcap'))
  THEN RAISE EXCEPTION 'donor 1 should list exactly the captured and the delivered gift; got %', ids; END IF;
  SELECT thread_open, unread_count, recipient_name INTO STRICT is_open, unread, nm FROM api.fn_my_threads() WHERE donation_id=(SELECT v::uuid FROM t WHERE k='dpaid');
  IF NOT is_open OR unread <> 1 OR nm <> 'Ana' THEN RAISE EXCEPTION 'delivered thread: open=% unread=% name=% (expected true,1,Ana)', is_open, unread, nm; END IF;
  IF (SELECT thread_open FROM api.fn_my_threads() WHERE donation_id=(SELECT v::uuid FROM t WHERE k='dcap')) THEN
    RAISE EXCEPTION 'a captured (not delivered) gift must not be open'; END IF;
  IF (SELECT campaign_title FROM api.fn_my_threads() WHERE donation_id=(SELECT v::uuid FROM t WHERE k='dpaid')) <> 'Ana sewing machine' THEN RAISE EXCEPTION 'campaign context missing'; END IF;
END $$;

DO $$ DECLARE got uuid[]; sts text[]; BEGIN
  -- messages: own messages in every status, recipient messages only when approved
  SELECT array_agg(id ORDER BY created_at, id), array_agg(moderation_status::text ORDER BY created_at, id) INTO got, sts
    FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dpaid'));
  IF (SELECT array_agg(x ORDER BY x) FROM unnest(got) x) IS DISTINCT FROM (SELECT array_agg(v::uuid ORDER BY v::uuid) FROM t WHERE k IN ('m1','m2','m3','m4'))
  THEN RAISE EXCEPTION 'donor 1 should see own 3 messages + the approved reply only; got % rows', array_length(got,1); END IF;
  IF NOT ('pending' = ANY(sts) AND 'rejected' = ANY(sts) AND 'approved' = ANY(sts)) THEN RAISE EXCEPTION 'own message statuses must be preserved: %', sts; END IF;
  -- not theirs / anonymous / not a thread / unpaid: no rows, no error, nothing revealed
  IF EXISTS (SELECT 1 FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dbpaid'))) THEN RAISE EXCEPTION 'donor 1 read donor 2''s thread'; END IF;
  IF EXISTS (SELECT 1 FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='danon'))) THEN RAISE EXCEPTION 'anonymous gift thread reachable through the signed-in door'; END IF;
  IF EXISTS (SELECT 1 FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dinit'))) OR EXISTS (SELECT 1 FROM api.fn_my_thread_messages(gen_random_uuid()))
  THEN RAISE EXCEPTION 'unpaid or unknown donation returned rows'; END IF;
END $$;

-- posting: not theirs, anonymous, unpaid, undelivered (captured) and unknown all give the SAME "thread not found" error; the delivery trigger is also checked directly
DO $$ DECLARE nm text; ok boolean; BEGIN
  FOREACH nm IN ARRAY ARRAY['dbpaid','danon','dinit','dfail','dcap'] LOOP
    ok := false;
    BEGIN PERFORM api.fn_my_post_message((SELECT v::uuid FROM t WHERE t.k=nm), decode(repeat('0b',40),'hex'));
    EXCEPTION WHEN invalid_authorization_specification THEN ok := true; END;
    IF NOT ok THEN RAISE EXCEPTION 'posting to % must fail with thread not found', nm; END IF;
  END LOOP;
  ok := false;
  BEGIN PERFORM api.fn_my_post_message(gen_random_uuid(), decode(repeat('0b',40),'hex'));
  EXCEPTION WHEN invalid_authorization_specification THEN ok := true; END;
  IF NOT ok THEN RAISE EXCEPTION 'posting to an unknown donation must fail with thread not found'; END IF;
  ok := false;
  RESET ROLE;                                                    -- the delivery trigger itself (defence in depth), as the owner would hit it
  BEGIN INSERT INTO core.anonymous_messages (donation_id,sender,body_enc) VALUES ((SELECT v::uuid FROM t WHERE k='dcap'),'donor',decode(repeat('0b',40),'hex'));
  EXCEPTION WHEN check_violation THEN ok := true; END;
  SET LOCAL ROLE sadqah_api;
  IF NOT ok THEN RAISE EXCEPTION 'posting before payout must be blocked by the delivery trigger'; END IF;
END $$;

-- posting on the delivered gift works, starts PENDING (moderation unchanged) and is capped at 10 donor messages per 24 hours (3 already seeded)
DO $$ DECLARE n int; mid uuid; ok boolean := false; st text; BEGIN
  mid := api.fn_my_post_message((SELECT v::uuid FROM t WHERE k='dpaid'), decode(repeat('0c',40),'hex'));
  INSERT INTO t VALUES ('mnew', mid::text);
  SELECT moderation_status::text INTO st FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dpaid')) WHERE id = mid;
  IF st <> 'pending' THEN RAISE EXCEPTION 'a new donor message must start pending, got %', st; END IF;
  FOR n IN 5..10 LOOP PERFORM api.fn_my_post_message((SELECT v::uuid FROM t WHERE k='dpaid'), decode(repeat('0d',40),'hex')); END LOOP;
  BEGIN PERFORM api.fn_my_post_message((SELECT v::uuid FROM t WHERE k='dpaid'), decode(repeat('0e',40),'hex'));
  EXCEPTION WHEN program_limit_exceeded THEN ok := true; END;
  IF NOT ok THEN RAISE EXCEPTION 'the 10-per-day limit was not enforced'; END IF;
END $$;

-- ===== mark-read: only the caller's own approved recipient replies ================================================================
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d2'),true);
DO $$ BEGIN PERFORM api.fn_my_mark_read((SELECT v::uuid FROM t WHERE k='dpaid')); END $$;     -- donor 2 tries to clear donor 1's unread
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d1'),true);
DO $$ BEGIN
  IF (SELECT unread_count FROM api.fn_my_threads() WHERE donation_id=(SELECT v::uuid FROM t WHERE k='dpaid')) <> 1 THEN RAISE EXCEPTION 'another donor cleared my unread count'; END IF;
  PERFORM api.fn_my_mark_read((SELECT v::uuid FROM t WHERE k='dpaid'));
  IF (SELECT unread_count FROM api.fn_my_threads() WHERE donation_id=(SELECT v::uuid FROM t WHERE k='dpaid')) <> 0 THEN RAISE EXCEPTION 'mark-read did not clear the unread count'; END IF;
  PERFORM api.fn_my_mark_read((SELECT v::uuid FROM t WHERE k='dbpaid'));                        -- donor 1 on donor 2's gift: a no-op
END $$;

-- ===== recipient reply -> approved -> donor unread goes up; the token door is untouched ===========================================
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='ra'),true);
DO $$ DECLARE rid uuid; BEGIN
  rid := api.fn_recipient_post_message((SELECT v::uuid FROM t WHERE k='dpaid'), decode(repeat('0f',40),'hex'));
  INSERT INTO t VALUES ('reply', rid::text);
  IF EXISTS (SELECT 1 FROM api.fn_my_threads()) THEN RAISE EXCEPTION 'a recipient account listed donor threads'; END IF;
  IF EXISTS (SELECT 1 FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dpaid'))) THEN RAISE EXCEPTION 'a recipient read donor threads through the donor door'; END IF;
  IF (SELECT count(*) FROM api.fn_recipient_thread_messages((SELECT v::uuid FROM t WHERE k='dpaid'))) < 1 THEN RAISE EXCEPTION 'recipient messaging stopped working'; END IF;
END $$;
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d1'),true);
DO $$ BEGIN
  IF (SELECT unread_count FROM api.fn_my_threads() WHERE donation_id=(SELECT v::uuid FROM t WHERE k='dpaid')) <> 0 THEN RAISE EXCEPTION 'a PENDING recipient reply counted as unread'; END IF;
  IF EXISTS (SELECT 1 FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dpaid')) WHERE id=(SELECT v::uuid FROM t WHERE k='reply')) THEN RAISE EXCEPTION 'a pending recipient reply reached the donor'; END IF;
END $$;
RESET ROLE;
SELECT core.fn_moderate_message((SELECT v::uuid FROM t WHERE k='reply'),'approved',NULL,(SELECT v::uuid FROM t WHERE k='rv'));
SET LOCAL ROLE sadqah_api;
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d1'),true);
DO $$ BEGIN
  IF (SELECT unread_count FROM api.fn_my_threads() WHERE donation_id=(SELECT v::uuid FROM t WHERE k='dpaid')) <> 1 THEN RAISE EXCEPTION 'an approved reply should be 1 unread'; END IF;
  IF NOT EXISTS (SELECT 1 FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dpaid')) WHERE id=(SELECT v::uuid FROM t WHERE k='reply')) THEN RAISE EXCEPTION 'approved reply not visible to the donor'; END IF;
END $$;

-- ===== donor 2 sees only their own; nobody signed in sees nothing ===============================================================
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d2'),true);
DO $$ BEGIN
  IF (SELECT array_agg(donation_id) FROM api.fn_my_threads()) IS DISTINCT FROM ARRAY[(SELECT v::uuid FROM t WHERE k='dbpaid')] THEN RAISE EXCEPTION 'donor 2 should list only their own gift'; END IF;
  IF EXISTS (SELECT 1 FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dpaid'))) THEN RAISE EXCEPTION 'donor 2 read donor 1''s thread'; END IF;
END $$;
SELECT set_config('app.current_user_id','',true);
DO $$ DECLARE ok boolean := false; BEGIN
  IF EXISTS (SELECT 1 FROM api.fn_my_threads()) OR EXISTS (SELECT 1 FROM api.fn_my_thread_messages((SELECT v::uuid FROM t WHERE k='dpaid'))) THEN RAISE EXCEPTION 'an unauthenticated session read threads'; END IF;
  BEGIN PERFORM api.fn_my_post_message((SELECT v::uuid FROM t WHERE k='dpaid'), decode(repeat('0b',40),'hex'));
  EXCEPTION WHEN invalid_authorization_specification THEN ok := true; END;
  IF NOT ok THEN RAISE EXCEPTION 'an unauthenticated session could post'; END IF;
END $$;

-- ===== anonymous token door: unchanged ============================================================================================
DO $$ BEGIN
  IF (SELECT count(*) FROM api.fn_track_thread(decode(repeat('ab',32),'hex'))) <> 2 THEN RAISE EXCEPTION 'token holder should still see their message and the approved reply'; END IF;
  IF EXISTS (SELECT 1 FROM api.fn_track_thread(decode(repeat('cd',32),'hex'))) THEN RAISE EXCEPTION 'a wrong token found a thread'; END IF;
  PERFORM api.fn_donor_post_message(decode(repeat('ab',32),'hex'), decode(repeat('10',40),'hex'));
END $$;

-- the public views never expose private messages (the web login can read no table; the views carry no message columns)
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='api' AND table_name LIKE 'public\_%' AND column_name IN ('body_enc','donation_id','read_by_donor_at')) THEN
    RAISE EXCEPTION 'a public view exposes private message columns'; END IF;
END $$;

ROLLBACK;
\echo donor_threads: all assertions passed
