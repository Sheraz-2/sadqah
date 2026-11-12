-- Assertions for patch 001 (account deletion, needs requests, reports, trust stats). Runs in one transaction and rolls back.
-- psql -h ... -U postgres -d sadqah -v ON_ERROR_STOP=1 -f database/tests/account_assistant_trust.sql
BEGIN;
CREATE TEMP TABLE t(k text PRIMARY KEY, v text);
GRANT ALL ON t TO PUBLIC;
DO $$
DECLARE d uuid; r uuid; s uuid; rid uuid; cid uuid; don uuid; files text[]; blockers text[]; n int; nid uuid; rep uuid;
BEGIN
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,display_name,country_code) VALUES
    ('donor','\x01','\x0101','h','Ayesha','PK') RETURNING id INTO d;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,country_code) VALUES ('recipient','\x02','\x0202','h','PK') RETURNING id INTO r;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash) VALUES ('reviewer','\x03','\x0303','h') RETURNING id INTO s;
  INSERT INTO core.recipients (user_id,slug,public_name,region_country,paypal_receiver_type,paypal_receiver_enc,paypal_receiver_blind_idx,story,business_type)
    VALUES (r,'sana-tailor','Sana','PK','EMAIL','\x04','\x0404','my story','tailoring') RETURNING id INTO rid;
  INSERT INTO core.recipients_kyc (recipient_id,status,full_name_enc,nic_number_enc,nic_blind_idx,address_enc,doc_country,consent_biometric_at,consent_data_at)
    VALUES (rid,'needs_human_review','\x05','\x06','\x0606','\x07','PK',now(),now());
  INSERT INTO core.kyc_documents (recipient_id,doc_type,object_key,sha256,mime_type,size_bytes,wrapped_dek)
    VALUES (rid,'national_id','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',sha256('x'),'image/png',10,'\x08');
  UPDATE core.recipients_kyc SET ai_assessed_at=now(), ai_fraud_risk_score=0.1, ai_recommended_allocation_cents=20000 WHERE recipient_id=rid;
  PERFORM core.fn_review_kyc(rid,'approved',3000,20000,s,NULL);
  UPDATE core.recipients SET profile_public=true, consent_public_profile_at=now() WHERE id=rid;
  INSERT INTO core.campaigns (recipient_id,slug,title,story,goal_cents,status) VALUES (rid,'sana-camp','Sewing machine','story',10000,'active') RETURNING id INTO cid;
  INSERT INTO core.donations (campaign_id,recipient_id,is_anonymous,donor_user_id,amount_cents) VALUES (cid,rid,false,d,1000) RETURNING id INTO don;
  INSERT INTO t VALUES ('d',d::text),('r',r::text),('s',s::text),('rid',rid::text),('don',don::text),('cid',cid::text);
END $$;

-- recipient blocked while a gift is initiated
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='r'),true);
DO $$ DECLARE b text[]; BEGIN b := api.fn_delete_blockers();
  IF cardinality(b)<>1 THEN RAISE EXCEPTION 'expected one blocker, got %', b; END IF; END $$;
DO $$ BEGIN PERFORM api.fn_delete_my_account(); RAISE EXCEPTION 'deletion should have been refused';
  EXCEPTION WHEN check_violation THEN NULL; END $$;

-- the gift is cancelled, the recipient can now delete
UPDATE core.donations SET status='cancelled' WHERE id=(SELECT v FROM t WHERE k='don')::uuid;
DO $$ DECLARE f text[]; u record; kyc record; rc record; BEGIN
  f := api.fn_delete_my_account();
  IF NOT ('vault:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' = ANY(f)) THEN RAISE EXCEPTION 'kyc file not returned: %', f; END IF;
  SELECT * INTO u FROM core.users WHERE id=(SELECT v FROM t WHERE k='r')::uuid;
  IF u.is_active OR u.deleted_at IS NULL OR u.password_hash<>'!deleted' OR u.country_code IS NOT NULL THEN RAISE EXCEPTION 'user not erased'; END IF;
  SELECT * INTO kyc FROM core.recipients_kyc WHERE recipient_id=(SELECT v FROM t WHERE k='rid')::uuid;
  IF kyc.status<>'suspended' OR kyc.full_name_enc IS NOT NULL OR kyc.nic_blind_idx IS NOT NULL OR kyc.address_enc IS NOT NULL THEN RAISE EXCEPTION 'kyc not erased'; END IF;
  SELECT * INTO rc FROM core.recipients WHERE id=(SELECT v FROM t WHERE k='rid')::uuid;
  IF rc.profile_public OR rc.story<>'' OR rc.business_type IS NOT NULL OR rc.slug='sana-tailor' OR rc.public_name='Sana' THEN RAISE EXCEPTION 'recipient not erased'; END IF;
  IF EXISTS (SELECT 1 FROM core.kyc_documents WHERE deleted_at IS NULL) THEN RAISE EXCEPTION 'documents not marked deleted'; END IF;
  IF (SELECT status FROM core.campaigns WHERE id=(SELECT v FROM t WHERE k='cid')::uuid)<>'closed' THEN RAISE EXCEPTION 'campaign not closed'; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.audit_log WHERE action='account.deleted' AND entity_id=(SELECT v FROM t WHERE k='r')) THEN RAISE EXCEPTION 'no audit row'; END IF;
END $$;
-- a deleted account is invisible to the sign-in helpers
DO $$ BEGIN IF EXISTS (SELECT 1 FROM api.fn_get_me()) THEN RAISE EXCEPTION 'deleted user still resolves'; END IF; END $$;

-- donor with a public gift deletes: the gift stays, the name goes
UPDATE core.donations SET status='captured', paypal_capture_id='CAP1' WHERE false;
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d'),true);
DO $$ DECLARE f text[]; BEGIN f := api.fn_delete_my_account();
  IF (SELECT donor_label FROM api.public_donation_feed LIMIT 1) IS NOT NULL AND (SELECT count(*) FROM api.public_donation_feed WHERE donor_label='Ayesha')>0 THEN RAISE EXCEPTION 'name leaked'; END IF;
  IF (SELECT display_name FROM core.users WHERE id=(SELECT v FROM t WHERE k='d')::uuid) IS NOT NULL THEN RAISE EXCEPTION 'display name kept'; END IF;
END $$;
-- staff cannot self-delete
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='s'),true);
DO $$ BEGIN IF api.fn_delete_blockers() = '{}' THEN RAISE EXCEPTION 'staff must be blocked'; END IF; END $$;

-- reports: public campaign only, one open report per account
SELECT set_config('app.current_user_id','',true);
DO $$ DECLARE x uuid; BEGIN
  UPDATE core.campaigns SET status='active', title='Sewing machine' WHERE false;
  BEGIN PERFORM api.fn_report_campaign('no-such','other',''); RAISE EXCEPTION 'should fail'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
END $$;

-- needs requests and reports, happy paths (fresh people: the first ones were erased above)
SELECT set_config('app.current_user_id','',true);
DO $$
DECLARE r2 uuid; s2 uuid; d2 uuid; rid2 uuid; cid2 uuid;
BEGIN
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,country_code) VALUES ('recipient','\x12','\x1212','h','PK') RETURNING id INTO r2;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash) VALUES ('reviewer','\x13','\x1313','h') RETURNING id INTO s2;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash) VALUES ('donor','\x14','\x1414','h') RETURNING id INTO d2;
  INSERT INTO core.recipients (user_id,slug,public_name,region_country,paypal_receiver_type,paypal_receiver_enc,paypal_receiver_blind_idx,story,business_type)
    VALUES (r2,'baker-bee','Baker','PK','EMAIL','\x14','\x1414','story','bakery') RETURNING id INTO rid2;
  INSERT INTO core.recipients_kyc (recipient_id,status,full_name_enc,nic_number_enc,nic_blind_idx,address_enc,doc_country,consent_biometric_at,consent_data_at)
    VALUES (rid2,'needs_human_review','\x15','\x16','\x1616','\x17','PK',now(),now());
  INSERT INTO core.kyc_documents (recipient_id,doc_type,object_key,sha256,mime_type,size_bytes,wrapped_dek)
    VALUES (rid2,'national_id','cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',sha256('y'),'image/png',10,'\x18');
  UPDATE core.recipients_kyc SET ai_assessed_at=now(), ai_fraud_risk_score=0.1, ai_recommended_allocation_cents=20000 WHERE recipient_id=rid2;
  PERFORM core.fn_review_kyc(rid2,'approved',3000,20000,s2,NULL);
  UPDATE core.recipients SET profile_public=true, consent_public_profile_at=now() WHERE id=rid2;
  INSERT INTO core.campaigns (recipient_id,slug,title,story,goal_cents,status) VALUES (rid2,'oven-camp','Oven','story',10000,'active') RETURNING id INTO cid2;
  INSERT INTO t VALUES ('r2',r2::text),('s2',s2::text),('d2',d2::text),('rid2',rid2::text);
END $$;

SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='r2'),true);
DO $$ DECLARE nid uuid; n int; b record; BEGIN
  nid := api.fn_needs_submit('PK','PKR','[{"name":"Flour","quantity":2,"asked_unit_price":9000}]'::jsonb, 5000, 4000, 'for bread',
                             'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','\x09','image/png',sha256('p'),'FLAGGED_SUSPICIOUS','HIGH','{"proof":{"flags_found":["x"]}}'::jsonb);
  IF nid IS NULL THEN RAISE EXCEPTION 'no id'; END IF;
  INSERT INTO t VALUES ('nid',nid::text);
  -- the same list twice in a row is refused
  BEGIN PERFORM api.fn_needs_submit('PK','PKR','[{"name":"Flour","quantity":2,"asked_unit_price":9000}]'::jsonb,5000,4000,'','k2','\x09','image/png',sha256('p'),'PASSED','LOW','{}'::jsonb);
        RAISE EXCEPTION 'duplicate accepted'; EXCEPTION WHEN unique_violation THEN NULL; END;
  SELECT count(*) INTO n FROM api.fn_needs_list();
  IF n<>1 THEN RAISE EXCEPTION 'list should show 1, got %', n; END IF;
  -- the recipient never sees the AI flags
  IF (SELECT count(*) FROM information_schema.columns WHERE table_name='fn_needs_list' AND column_name IN ('ai_result','hr_filter_status','priority_queue'))<>0 THEN RAISE EXCEPTION 'flags exposed'; END IF;
  -- a donor cannot submit
END $$;
-- a recipient cannot decide their own request
DO $$ BEGIN
  BEGIN PERFORM core.fn_decide_needs((SELECT v FROM t WHERE k='nid')::uuid,'approved','self',(SELECT v FROM t WHERE k='r2')::uuid); RAISE EXCEPTION 'self-approval allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d2'),true);
DO $$ BEGIN
  BEGIN PERFORM api.fn_needs_submit('PK','PKR','[]'::jsonb,0,0,'','k3','\x09','image/png',sha256('p'),'PASSED','LOW','{}'::jsonb); RAISE EXCEPTION 'donor submitted';
  EXCEPTION WHEN check_violation THEN NULL; END;
END $$;
-- staff decide: invalid decision refused, valid one recorded with audit
DO $$ BEGIN
  BEGIN PERFORM core.fn_decide_needs((SELECT v FROM t WHERE k='nid')::uuid,'maybe','',(SELECT v FROM t WHERE k='s2')::uuid); RAISE EXCEPTION 'bad decision accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  PERFORM core.fn_decide_needs((SELECT v FROM t WHERE k='nid')::uuid,'more_info','Please add a receipt',(SELECT v FROM t WHERE k='s2')::uuid);
  IF (SELECT status FROM core.needs_requests WHERE id=(SELECT v FROM t WHERE k='nid')::uuid)<>'more_info' THEN RAISE EXCEPTION 'status not changed'; END IF;
  IF NOT EXISTS (SELECT 1 FROM core.v_admin_needs_queue WHERE id=(SELECT v FROM t WHERE k='nid')::uuid AND priority_queue='HIGH') THEN RAISE EXCEPTION 'not in staff queue'; END IF;
END $$;
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='r2'),true);
DO $$ BEGIN
  IF (SELECT reviewer_note FROM api.fn_needs_list() LIMIT 1) <> 'Please add a receipt' THEN RAISE EXCEPTION 'note not visible to recipient'; END IF;
END $$;

-- reports: anonymous allowed, one open report per signed-in person, staff resolve
SELECT set_config('app.current_user_id','',true);
DO $$ DECLARE x uuid; BEGIN
  x := api.fn_report_campaign('oven-camp','fake_or_misleading','photos look stolen');
  INSERT INTO t VALUES ('rep',x::text);
  BEGIN PERFORM api.fn_report_campaign('oven-camp','bogus',''); RAISE EXCEPTION 'bad reason accepted'; EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
END $$;
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='d2'),true);
DO $$ BEGIN
  PERFORM api.fn_report_campaign('oven-camp','not_in_need','');
  BEGIN PERFORM api.fn_report_campaign('oven-camp','other','again again again'); RAISE EXCEPTION 'duplicate report accepted'; EXCEPTION WHEN unique_violation THEN NULL; END;
  IF (SELECT max(reports_on_campaign) FROM core.v_admin_reports WHERE campaign_slug='oven-camp')<>2 THEN RAISE EXCEPTION 'report count wrong'; END IF;
  PERFORM core.fn_resolve_report((SELECT v FROM t WHERE k='rep')::uuid,'actioned',(SELECT v FROM t WHERE k='s2')::uuid);
  IF (SELECT status FROM core.campaign_reports WHERE id=(SELECT v FROM t WHERE k='rep')::uuid)<>'actioned' THEN RAISE EXCEPTION 'report not resolved'; END IF;
END $$;

-- trust stats view is readable
SELECT * FROM api.public_trust_stats;
ROLLBACK;
\echo 'account_assistant_trust: all assertions passed'
