-- =============================================================================
-- SadQah | database/tests/flow_and_privacy.sql
--
-- End-to-end proof that the DATABASE (not only the application) enforces the rules.
-- Runs the whole life of a donation as each service role, then tries to break the
-- privacy guarantees and checks that every attempt fails.
--
--   psql -v ON_ERROR_STOP=1 -d sadqah -f database/tests/flow_and_privacy.sql
--
-- Run as a superuser on a database that already has roles.sql + schema.sql applied.
-- Everything happens inside one transaction that is rolled back, so it leaves no data.
-- =============================================================================
\set ON_ERROR_STOP on
\set QUIET on
BEGIN;

-- ---------------------------------------------------------------- actors ---------
RESET ROLE;
INSERT INTO core.users (role, email_enc, email_blind_idx, password_hash, display_name)
VALUES ('reviewer', '\x01', '\x01', 'x', 'Reviewer') RETURNING id AS reviewer_id \gset

SET ROLE sadqah_api;
SELECT api.fn_register_user('\x02', '\x02', NULL, NULL, 'x', 'donor', 'Amina Donor', 'GB') AS donor_id \gset
SELECT api.fn_register_user('\x03', '\x03', NULL, NULL, 'x', 'recipient', NULL, 'PK') AS rec_user_id \gset
-- self-registration can never mint staff
DO $$ BEGIN
  PERFORM api.fn_register_user('\x04', '\x04', NULL, NULL, 'x', 'admin', NULL, 'PK');
  RAISE EXCEPTION 'privilege escalation through registration';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;

-- ------------------------------------------------ recipient onboarding + KYC -----
SELECT set_config('app.current_user_id', :'rec_user_id', false);
SELECT api.fn_create_recipient_profile('bilal-tailor', 'Bilal', 'I stitch school uniforms.', 'tailoring', 'PK',
                                       'Punjab', 'EMAIL', '\xaa', '\xbb') AS rec_id \gset
SELECT api.fn_kyc_save_identity('\x10', '\x11', '\x12', '\x13', '\x14', 'PK', true, true);
SELECT api.fn_kyc_register_document('national_id',    'obj-1', decode(repeat('11', 32), 'hex'), 'image/jpeg', 1000, '\x01');
SELECT api.fn_kyc_register_document('utility_bill',   'obj-2', decode(repeat('22', 32), 'hex'), 'application/pdf', 1000, '\x01');
SELECT api.fn_kyc_register_document('selfie',         'obj-3', decode(repeat('33', 32), 'hex'), 'image/jpeg', 1000, '\x01');
-- not complete yet: no proof of income
SELECT cardinality(api.fn_kyc_submit()) = 1 AS ok \gset
\if :ok
\else
  \echo FAIL: submit should report exactly one missing document
  SELECT 1/0;
\endif
SELECT api.fn_kyc_register_document('bank_statement', 'obj-4', decode(repeat('44', 32), 'hex'), 'application/pdf', 1000, '\x01');
SELECT cardinality(api.fn_kyc_submit()) = 0 AS ok \gset
\if :ok
\else
  \echo FAIL: submit should succeed with all documents
  SELECT 1/0;
\endif

-- AI pipeline (can only recommend)
SET ROLE sadqah_kyc;
SELECT core.fn_store_kyc_assessment(:'rec_id', 3000, 0.93, 0.08, '[]'::jsonb, 20000, 'test-model');
-- the pipeline role cannot approve anything
DO $$ BEGIN
  UPDATE core.recipients_kyc SET status = 'approved';
  RAISE EXCEPTION 'KYC pipeline role was able to write recipients_kyc';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;

-- human decision. Income of $50+ can never be approved (CHECK constraint), even by staff.
RESET ROLE;
SELECT set_config('test.reviewer', :'reviewer_id', false), set_config('test.rec_id', :'rec_id', false);
SET ROLE sadqah_admin;
DO $$ BEGIN
  PERFORM core.fn_review_kyc(current_setting('test.rec_id')::uuid, 'approved', 6000, 20000,
                             current_setting('test.reviewer')::uuid, 'x');
  RAISE EXCEPTION 'approved an income above the distress threshold';
EXCEPTION WHEN check_violation THEN NULL; END $$;
SELECT core.fn_review_kyc(:'rec_id', 'approved', 3000, 20000, :'reviewer_id', 'documents consistent');

-- ------------------------------------------------ campaign ----------------------
SET ROLE sadqah_api;
SELECT set_config('app.current_user_id', :'rec_user_id', false);
SELECT api.fn_set_profile_public(true);
SELECT api.fn_create_campaign('bilal-sewing-machine', 'A sewing machine for Bilal', 'story', 20000);
DO $$ BEGIN
  PERFORM api.fn_create_campaign('another-one', 'second live campaign', 's', 10000);
  RAISE EXCEPTION 'two live campaigns allowed';
EXCEPTION WHEN unique_violation THEN NULL; END $$;

-- ------------------------------------------------ donations ---------------------
SELECT set_config('app.current_user_id', :'donor_id', false);
SELECT api.fn_create_donation('bilal-sewing-machine', 1000, false, :'donor_id', NULL) AS d_public \gset
SELECT api.fn_attach_paypal_order(:'d_public', 'ORDER-PUBLIC');

SELECT set_config('app.current_user_id', '', false);          -- no session at all
SELECT api.fn_create_donation('bilal-sewing-machine', 2500, true, NULL, decode(repeat('ab', 32), 'hex')) AS d_anon \gset
SELECT api.fn_attach_paypal_order(:'d_anon', 'ORDER-ANON');

-- an anonymous gift that names a donor is refused, in the function and in the table
DO $$ BEGIN
  PERFORM api.fn_create_donation('bilal-sewing-machine', 500, true, gen_random_uuid(), decode(repeat('cd', 32), 'hex'));
  RAISE EXCEPTION 'anonymous donation accepted a donor id';
EXCEPTION WHEN check_violation THEN NULL; END $$;
RESET ROLE;
DO $$ BEGIN
  INSERT INTO core.donations (campaign_id, recipient_id, is_anonymous, donor_user_id, tracking_token_hash, amount_cents)
  SELECT c.id, c.recipient_id, true, (SELECT id FROM core.users WHERE role = 'donor'), decode(repeat('ee', 32), 'hex'), 500
    FROM core.campaigns c LIMIT 1;
  RAISE EXCEPTION 'table accepted an anonymous row with a donor id';
EXCEPTION WHEN check_violation THEN NULL; END $$;

-- not yet captured: tracking token finds nothing
SET ROLE sadqah_api;
SELECT count(*) = 0 AS ok FROM api.fn_track_donation(decode(repeat('ab', 32), 'hex')) \gset
\if :ok
\else
  \echo FAIL: uncaptured donation must not be trackable
  SELECT 1/0;
\endif

-- ------------------------------------------------ capture (webhook role) --------
SET ROLE sadqah_webhook;
SELECT core.fn_mark_donation_captured(:'d_public', 'CAP-1', 1000, '\x99') AS first \gset
SELECT core.fn_mark_donation_captured(:'d_public', 'CAP-1', 1000, '\x99') AS replay \gset
SELECT core.fn_mark_donation_captured(:'d_anon',   'CAP-2', 2500, '\x98');
\if :first
\else
  \echo FAIL: first capture should return true
  SELECT 1/0;
\endif
\if :replay
  \echo FAIL: a replayed capture must be a harmless no-op
  SELECT 1/0;
\endif
-- a captured amount that differs from the bound donation is refused
SET ROLE sadqah_api;
SELECT set_config('app.current_user_id', '', false);
SELECT api.fn_create_donation('bilal-sewing-machine', 700, true, NULL, decode(repeat('a1', 32), 'hex')) AS d_mismatch \gset
RESET ROLE;
SELECT set_config('test.mismatch', :'d_mismatch', false);
SET ROLE sadqah_webhook;
DO $$ BEGIN
  PERFORM core.fn_mark_donation_captured(current_setting('test.mismatch')::uuid, 'CAP-X', 999, NULL);
  RAISE EXCEPTION 'a capture with the wrong amount was accepted';
EXCEPTION WHEN check_violation THEN NULL; END $$;

-- ------------------------------------------------ public views never leak -------
SET ROLE sadqah_api;
SELECT count(*) = 1 AS ok FROM api.public_leaderboard \gset
\if :ok
\else
  \echo FAIL: leaderboard must contain the public donor only
  SELECT 1/0;
\endif
SELECT count(*) = 1 AS ok FROM api.public_donation_feed WHERE is_anonymous AND donor_label = 'Anonymous' \gset
\if :ok
\else
  \echo FAIL: anonymous gift must be labelled Anonymous in the feed
  SELECT 1/0;
\endif
SELECT count(*) = 0 AS ok FROM api.public_donation_feed WHERE is_anonymous AND given_at <> date_trunc('day', given_at) \gset
\if :ok
\else
  \echo FAIL: anonymous timestamps must be truncated to the day
  SELECT 1/0;
\endif
-- the API role has no table rights at all
DO $$ BEGIN PERFORM 1 FROM core.donations;   RAISE EXCEPTION 'api read donations';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
DO $$ BEGIN PERFORM 1 FROM core.users;      RAISE EXCEPTION 'api read users';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
DO $$ BEGIN PERFORM 1 FROM core.payout_queue; RAISE EXCEPTION 'api read payout_queue';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
DO $$ BEGIN PERFORM 1 FROM core.anonymous_messages; RAISE EXCEPTION 'api read messages';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;

-- ------------------------------------------------ payout batching (worker) ------
SET ROLE sadqah_worker;
SELECT ready_count = 2 AS ok FROM core.fn_payout_queue_stats() \gset
\if :ok
\else
  \echo FAIL: two payouts should be ready
  SELECT 1/0;
\endif
-- the worker cannot read donors or donations
DO $$ BEGIN PERFORM 1 FROM core.donations; RAISE EXCEPTION 'worker read donations';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
SELECT core.fn_claim_payout_batch(100, 'SQ-TEST-BATCH-1') AS batch_id \gset
SELECT count(*) = 2 AS ok FROM core.fn_get_batch_items(:'batch_id') \gset
\if :ok
\else
  \echo FAIL: batch should contain both payouts
  SELECT 1/0;
\endif
-- a second claim finds nothing (no double payment)
SELECT core.fn_claim_payout_batch(100, 'SQ-TEST-BATCH-2') IS NULL AS ok \gset
\if :ok
\else
  \echo FAIL: claimed rows must not be claimed twice
  SELECT 1/0;
\endif
SELECT core.fn_mark_batch_submitted(:'batch_id', 'PAYPAL-BATCH-1');
SELECT core.fn_batch_submission_failed(:'batch_id', 'late failure', true, 6) IS NULL AS ok \gset
\if :ok
\else
  \echo FAIL: a submitted batch cannot be failed by a stale retry
  SELECT 1/0;
\endif

-- ------------------------------------------------ webhooks reconcile the ledger --
SET ROLE sadqah_webhook;
SELECT core.fn_record_webhook('WH-1', 'PAYMENT.PAYOUTS-ITEM.SUCCEEDED', 'PI-1',
        '{"resource":{"payout_item":{"receiver":"secret@example.com","sender_item_id":"x"},"payer":{"email":"p@x.com"}}}'::jsonb) AS fresh \gset
SELECT core.fn_record_webhook('WH-1', 'PAYMENT.PAYOUTS-ITEM.SUCCEEDED', 'PI-1', '{}'::jsonb) AS replay \gset
\if :fresh
\else
  \echo FAIL: first webhook should be recorded
  SELECT 1/0;
\endif
\if :replay
  \echo FAIL: a replayed webhook must be ignored
  SELECT 1/0;
\endif
SELECT core.fn_apply_payout_item_event(:'d_anon',   'succeeded', 'PI-A', 'SUCCESS',   NULL, 'WH-2') AS ok \gset
\if :ok
\else
  \echo FAIL: anonymous payout should settle
  SELECT 1/0;
\endif
SELECT core.fn_apply_payout_item_event(:'d_public', 'unclaimed', 'PI-B', 'UNCLAIMED', NULL, 'WH-3');
SELECT core.fn_apply_payout_item_event(:'d_public', 'succeeded', 'PI-B', 'SUCCESS',   NULL, 'WH-4') AS ok \gset
\if :ok
\else
  \echo FAIL: an unclaimed payout must be able to succeed once claimed
  SELECT 1/0;
\endif
-- out-of-order / illegal transition is a safe no-op
SELECT core.fn_apply_payout_item_event(:'d_public', 'queued', NULL, NULL, NULL, 'WH-5') AS applied \gset
\if :applied
  \echo FAIL: illegal transition applied
  SELECT 1/0;
\endif
SELECT core.fn_apply_batch_event('SQ-TEST-BATCH-1', 'PAYPAL-BATCH-1', 'success', 'WH-6');
-- the stored webhook payload was scrubbed of receiver and payer data
RESET ROLE;
SELECT count(*) = 0 AS ok FROM core.webhook_events
 WHERE payload::text LIKE '%secret@example.com%' OR payload::text LIKE '%p@x.com%' \gset
\if :ok
\else
  \echo FAIL: webhook payload kept receiver or payer data
  SELECT 1/0;
\endif

-- real-time reconciliation happened without anyone touching it
SELECT (SELECT status FROM core.donations WHERE id = :'d_anon') = 'paid_out'
   AND (SELECT status FROM core.donations WHERE id = :'d_public') = 'paid_out'
   AND (SELECT paid_out_cents FROM core.campaigns WHERE slug = 'bilal-sewing-machine') = 3500
   AND (SELECT raised_cents   FROM core.campaigns WHERE slug = 'bilal-sewing-machine') = 3500 AS ok \gset
\if :ok
\else
  \echo FAIL: donation and campaign totals did not reconcile
  SELECT 1/0;
\endif
SELECT count(*) = 0 AS ok FROM core.v_admin_reconciliation WHERE raised_mismatch OR paid_out_mismatch \gset
\if :ok
\else
  \echo FAIL: reconciliation view shows a mismatch
  SELECT 1/0;
\endif
SELECT count(*) >= 6 AS ok FROM core.ledger_events WHERE donation_id IN (:'d_anon'::uuid, :'d_public'::uuid) \gset
\if :ok
\else
  \echo FAIL: ledger is missing events
  SELECT 1/0;
\endif

-- ------------------------------------------------ anonymous tracking & messaging --
SET ROLE sadqah_api;
SELECT set_config('app.current_user_id', '', false);
SELECT count(*) = 1 AND bool_and(delivery_state = 'delivered') AND bool_and(thread_open)
       AND bool_and(recipient_slug = 'bilal-tailor') AS ok
  FROM api.fn_track_donation(decode(repeat('ab', 32), 'hex')) \gset
\if :ok
\else
  \echo FAIL: token holder should see a delivered gift and the recipient
  SELECT 1/0;
\endif
SELECT count(*) = 0 AS ok FROM api.fn_track_donation(decode(repeat('00', 32), 'hex')) \gset
\if :ok
\else
  \echo FAIL: wrong token must find nothing
  SELECT 1/0;
\endif

SELECT api.fn_donor_post_message(decode(repeat('ab', 32), 'hex'), decode(repeat('00', 40), 'hex')) AS msg_id \gset
-- pending messages are invisible to the recipient until moderated
SELECT set_config('app.current_user_id', :'rec_user_id', false);
SELECT count(*) = 0 AS ok FROM api.fn_recipient_thread_messages(:'d_anon') \gset
\if :ok
\else
  \echo FAIL: unmoderated donor message leaked to the recipient
  SELECT 1/0;
\endif
SET ROLE sadqah_admin;
SELECT core.fn_moderate_message(:'msg_id', 'approved', NULL, :'reviewer_id');
SET ROLE sadqah_api;
SELECT set_config('app.current_user_id', :'rec_user_id', false);
SELECT count(*) = 1 AS ok FROM api.fn_recipient_thread_messages(:'d_anon') \gset
\if :ok
\else
  \echo FAIL: approved message should reach the recipient
  SELECT 1/0;
\endif
-- the recipient's view of the anonymous donor is generic, with the time truncated to the day
SELECT bool_and(donor_label = 'A SadQah donor') FILTER (WHERE is_anonymous)
       AND bool_and(paid_out_at = date_trunc('day', paid_out_at)) FILTER (WHERE is_anonymous) AS ok
  FROM api.fn_recipient_threads() \gset
\if :ok
\else
  \echo FAIL: recipient thread list leaks donor identity or exact time
  SELECT 1/0;
\endif
SELECT api.fn_recipient_post_message(:'d_anon', decode(repeat('01', 40), 'hex')) AS reply_id \gset
SELECT api.fn_post_gratitude(:'d_anon', 'Thank you, whoever you are.') AS g_anon \gset
SELECT api.fn_post_gratitude(:'d_public', 'Thank you Amina!') AS g_pub \gset
SET ROLE sadqah_admin;
SELECT core.fn_moderate_message(:'reply_id', 'approved', NULL, :'reviewer_id');
SELECT core.fn_moderate_gratitude(:'g_anon', 'approved', :'reviewer_id');
SELECT core.fn_moderate_gratitude(:'g_pub',  'approved', :'reviewer_id');
SET ROLE sadqah_api;
SELECT set_config('app.current_user_id', '', false);
SELECT count(*) = 2 AS ok FROM api.fn_track_thread(decode(repeat('ab', 32), 'hex')) \gset
\if :ok
\else
  \echo FAIL: token holder should see their message and the recipient reply
  SELECT 1/0;
\endif
SELECT count(*) FILTER (WHERE thanks_to = 'the SadQah community') = 1
       AND count(*) FILTER (WHERE thanks_to = 'Amina Donor') = 1 AS ok FROM api.public_gratitude_wall \gset
\if :ok
\else
  \echo FAIL: gratitude audience must follow the donor privacy choice
  SELECT 1/0;
\endif
SELECT set_config('app.current_user_id', :'donor_id', false);
SELECT count(*) = 1 AS ok FROM api.my_gratitude \gset
\if :ok
\else
  \echo FAIL: the public donor should receive their direct thank-you
  SELECT 1/0;
\endif
SELECT count(*) = 1 AS ok FROM api.my_donations \gset
\if :ok
\else
  \echo FAIL: my_donations must list only the public gift (anonymous gifts have no owner)
  SELECT 1/0;
\endif

-- ------------------------------------------------ immutability --------------------
RESET ROLE;
DO $$ BEGIN
  UPDATE core.donations SET donor_user_id = (SELECT id FROM core.users WHERE role = 'donor') WHERE is_anonymous;
  RAISE EXCEPTION 'de-anonymisation by UPDATE succeeded';
EXCEPTION WHEN check_violation THEN NULL; END $$;
DO $$ BEGIN
  UPDATE core.ledger_events SET amount_cents = 1;
  RAISE EXCEPTION 'ledger row was modified';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;
DO $$ BEGIN
  DELETE FROM core.audit_log;
  RAISE EXCEPTION 'audit log row was deleted';
EXCEPTION WHEN insufficient_privilege THEN NULL; END $$;

\echo ALL DATABASE PRIVACY AND FLOW CHECKS PASSED
ROLLBACK;
