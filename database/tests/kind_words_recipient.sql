-- Assertions for GET /recipient/kind-words (Phase 4C): a recipient sees only the APPROVED public comments on their OWN campaign(s),
-- newest first. Runs in one transaction and rolls back. Needs a database built from schema.sql, roles.sql and patches/.
-- psql -h ... -U postgres -d sadqah -v ON_ERROR_STOP=1 -f database/tests/kind_words_recipient.sql
-- The query below must stay identical to _KIND_WORDS in backend/app/api/routes/recipient.py (a backend test compares them).
BEGIN;
CREATE TEMP TABLE t(k text PRIMARY KEY, v text);
GRANT ALL ON t TO PUBLIC;
DO $$
DECLARE d1 uuid; d2 uuid; ra uuid; rb uuid; rc uuid; sa uuid; sb uuid; staff uuid; cida uuid; cidb uuid;
BEGIN
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,display_name,country_code) VALUES ('donor','\x01','\x0101','h','Ayesha','PK') RETURNING id INTO d1;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,country_code) VALUES ('donor','\x11','\x1101','h','PK') RETURNING id INTO d2;   -- no display name
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,country_code) VALUES ('recipient','\x02','\x0202','h','PK') RETURNING id INTO ra;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,country_code) VALUES ('recipient','\x12','\x1202','h','PK') RETURNING id INTO rb;
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash,country_code) VALUES ('recipient','\x22','\x2202','h','PK') RETURNING id INTO rc;   -- no campaign
  INSERT INTO core.users (role,email_enc,email_blind_idx,password_hash) VALUES ('reviewer','\x03','\x0303','h') RETURNING id INTO staff;

  INSERT INTO core.recipients (user_id,slug,public_name,region_country,paypal_receiver_type,paypal_receiver_enc,paypal_receiver_blind_idx,story,business_type)
    VALUES (ra,'kw-a','Ana','PK','EMAIL','\x04','\x0404','story','tailoring') RETURNING id INTO sa;
  INSERT INTO core.recipients (user_id,slug,public_name,region_country,paypal_receiver_type,paypal_receiver_enc,paypal_receiver_blind_idx,story,business_type)
    VALUES (rb,'kw-b','Bo','PK','EMAIL','\x14','\x1404','story','baking') RETURNING id INTO sb;
  FOR i IN 1..2 LOOP
    INSERT INTO core.recipients_kyc (recipient_id,status,full_name_enc,nic_number_enc,nic_blind_idx,address_enc,doc_country,consent_biometric_at,consent_data_at)
      VALUES (CASE i WHEN 1 THEN sa ELSE sb END,'needs_human_review','\x05','\x06',decode('06' || lpad(i::text,2,'0'),'hex'),'\x07','PK',now(),now());
    INSERT INTO core.kyc_documents (recipient_id,doc_type,object_key,sha256,mime_type,size_bytes,wrapped_dek)
      VALUES (CASE i WHEN 1 THEN sa ELSE sb END,'national_id',repeat(CASE i WHEN 1 THEN 'a' ELSE 'b' END,68),sha256('x'),'image/png',10,'\x08');
    UPDATE core.recipients_kyc SET ai_assessed_at=now(), ai_fraud_risk_score=0.1, ai_recommended_allocation_cents=20000
     WHERE recipient_id=CASE i WHEN 1 THEN sa ELSE sb END;
    PERFORM core.fn_review_kyc(CASE i WHEN 1 THEN sa ELSE sb END,'approved',3000,20000,staff,NULL);
  END LOOP;
  UPDATE core.recipients SET profile_public=true, consent_public_profile_at=now() WHERE id IN (sa,sb);
  INSERT INTO core.campaigns (recipient_id,slug,title,story,goal_cents,status) VALUES (sa,'kw-a-camp','A camp','story',10000,'active') RETURNING id INTO cida;
  INSERT INTO core.campaigns (recipient_id,slug,title,story,goal_cents,status) VALUES (sb,'kw-b-camp','B camp','story',10000,'active') RETURNING id INTO cidb;

  INSERT INTO core.campaign_comments (campaign_id,author_user_id,body,moderation_status,created_at) VALUES
    (cida,d1,'a-old','approved',now() - interval '2 days'),
    (cida,d2,'a-new','approved',now() - interval '1 hour'),
    (cida,d1,'a-pending','pending',now()),
    (cida,d1,'a-rejected','rejected',now()),
    (cidb,d1,'b-one','approved',now());
  INSERT INTO t VALUES ('ra',ra::text),('rb',rb::text),('rc',rc::text);
END $$;

-- run exactly as the web API would: the least-privilege login, with the signed-in user set per request
SET LOCAL ROLE sadqah_api;

-- recipient A: only A's approved comments, newest first, with the public display names
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='ra'),true);
DO $$ DECLARE r record; bodies text[] := '{}'; names text[] := '{}'; slugs text[] := '{}'; BEGIN
  FOR r IN SELECT cm.id, cm.campaign_slug, cm.author_name, cm.body, cm.created_at FROM api.public_campaign_comments cm
            WHERE cm.campaign_slug IN (SELECT slug FROM api.my_campaign) ORDER BY cm.created_at DESC LIMIT 100 LOOP
    bodies := bodies || r.body; names := names || r.author_name; slugs := slugs || r.campaign_slug;
  END LOOP;
  IF bodies <> ARRAY['a-new','a-old'] THEN RAISE EXCEPTION 'recipient A should see exactly the approved comments, newest first; got %', bodies; END IF;
  IF names <> ARRAY['SadQah friend','Ayesha'] THEN RAISE EXCEPTION 'unexpected display names: %', names; END IF;
  IF slugs <> ARRAY['kw-a-camp','kw-a-camp'] THEN RAISE EXCEPTION 'comment from another campaign leaked: %', slugs; END IF;
END $$;

-- recipient B sees only B's comment, never A's
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='rb'),true);
DO $$ DECLARE bodies text[]; BEGIN
  SELECT array_agg(cm.body ORDER BY cm.created_at DESC) INTO bodies FROM api.public_campaign_comments cm
   WHERE cm.campaign_slug IN (SELECT slug FROM api.my_campaign);
  IF bodies IS DISTINCT FROM ARRAY['b-one'] THEN RAISE EXCEPTION 'recipient B should see only their own comment; got %', bodies; END IF;
END $$;

-- a recipient with no campaign sees nothing
SELECT set_config('app.current_user_id',(SELECT v FROM t WHERE k='rc'),true);
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM api.public_campaign_comments cm WHERE cm.campaign_slug IN (SELECT slug FROM api.my_campaign);
  IF n <> 0 THEN RAISE EXCEPTION 'a recipient without a campaign saw % comments', n; END IF;
END $$;

-- no signed-in user: nothing
SELECT set_config('app.current_user_id','',true);
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM api.public_campaign_comments cm WHERE cm.campaign_slug IN (SELECT slug FROM api.my_campaign);
  IF n <> 0 THEN RAISE EXCEPTION 'an unauthenticated session saw % comments', n; END IF;
END $$;

-- the public campaign comments view is unchanged: approved only, per campaign
DO $$ DECLARE na int; nb int; BEGIN
  SELECT count(*) INTO na FROM api.public_campaign_comments WHERE campaign_slug='kw-a-camp';
  SELECT count(*) INTO nb FROM api.public_campaign_comments WHERE campaign_slug='kw-b-camp';
  IF na <> 2 OR nb <> 1 THEN RAISE EXCEPTION 'public comments view changed: A=% B=%', na, nb; END IF;
END $$;

ROLLBACK;
\echo kind_words_recipient: all assertions passed
