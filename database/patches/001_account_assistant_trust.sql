-- =============================================================================
-- Patch 001: account settings (delete my account), the needs check (AI assistant),
--            campaign reports, and public trust statistics.
--
-- Additive and idempotent: safe to run more than once, never drops or rewrites existing data.
-- Applied automatically on a FRESH database by `docker compose up` (db-init). On an EXISTING database run:
--   Get-Content database\patches\001_account_assistant_trust.sql | docker compose exec -T db psql -U postgres -d sadqah -v ON_ERROR_STOP=1
-- =============================================================================

SET ROLE sadqah_owner;

BEGIN;

-- ---- 1. users: a marker for deleted accounts ---------------------------------------------------------------------
ALTER TABLE core.users ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

-- ---- 2. needs requests (the recipient's itemised "what I need" list, checked by the assistant, decided by a human) ----
CREATE TABLE IF NOT EXISTS core.needs_requests (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id            uuid NOT NULL REFERENCES core.recipients(id) ON DELETE RESTRICT,
    status                  text NOT NULL DEFAULT 'submitted'
                                CHECK (status IN ('submitted', 'approved', 'declined', 'more_info')),
    country                 char(2) NOT NULL,
    local_currency          char(3),
    items                   jsonb NOT NULL
                                CHECK (jsonb_typeof(items) = 'array' AND jsonb_array_length(items) BETWEEN 1 AND 30),
    requested_total_cents   bigint NOT NULL CHECK (requested_total_cents >= 0),     -- what the person asked for, USD (approximate conversion)
    estimated_total_cents   bigint CHECK (estimated_total_cents >= 0),              -- the assistant's typical local-market estimate, USD
    explanation             text NOT NULL DEFAULT '' CHECK (char_length(explanation) <= 2000),
    proof_object_key        text UNIQUE,
    proof_wrapped_dek       bytea,
    proof_mime              text CHECK (proof_mime IS NULL OR proof_mime IN ('image/jpeg', 'image/png', 'application/pdf')),
    proof_sha256            bytea CHECK (proof_sha256 IS NULL OR octet_length(proof_sha256) = 32),
    hr_filter_status        text CHECK (hr_filter_status IN ('PASSED', 'FLAGGED_SUSPICIOUS', 'FAILED_IRRELEVANT', 'NOT_CHECKED')),
    priority_queue          text CHECK (priority_queue IN ('HIGH', 'MEDIUM', 'LOW')),
    ai_result               jsonb NOT NULL DEFAULT '{}'::jsonb,
    reviewer_id             uuid REFERENCES core.users(id) ON DELETE RESTRICT,
    reviewed_at             timestamptz,
    reviewer_note           text CHECK (reviewer_note IS NULL OR char_length(reviewer_note) <= 500),
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_needs_recipient ON core.needs_requests (recipient_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_needs_open ON core.needs_requests (created_at) WHERE status = 'submitted';
ALTER TABLE core.needs_requests ENABLE ROW LEVEL SECURITY;
DROP TRIGGER IF EXISTS trg_needs_touch ON core.needs_requests;
CREATE TRIGGER trg_needs_touch BEFORE UPDATE ON core.needs_requests
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

-- ---- 3. campaign reports ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.campaign_reports (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id         uuid NOT NULL REFERENCES core.campaigns(id) ON DELETE RESTRICT,
    reporter_user_id    uuid REFERENCES core.users(id) ON DELETE RESTRICT,      -- NULL when reported without an account
    reason              text NOT NULL CHECK (reason IN ('fake_or_misleading', 'not_in_need', 'impersonation', 'inappropriate', 'other')),
    details             text NOT NULL DEFAULT '' CHECK (char_length(details) <= 1000),
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'dismissed', 'actioned')),
    reviewer_id         uuid REFERENCES core.users(id) ON DELETE RESTRICT,
    reviewed_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reports_open ON core.campaign_reports (created_at) WHERE status = 'open';
CREATE UNIQUE INDEX IF NOT EXISTS uq_report_once ON core.campaign_reports (campaign_id, reporter_user_id)
    WHERE reporter_user_id IS NOT NULL AND status = 'open';
ALTER TABLE core.campaign_reports ENABLE ROW LEVEL SECURITY;

-- ---- 4. staff views ----------------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW core.v_admin_needs_queue AS
SELECT n.id, n.recipient_id, n.status, n.country, n.local_currency, n.items, n.requested_total_cents,
       n.estimated_total_cents, n.explanation, n.hr_filter_status, n.priority_queue, n.ai_result,
       (n.proof_object_key IS NOT NULL) AS has_proof, n.proof_mime,
       n.reviewer_note, n.reviewed_at, n.created_at,
       r.public_name, r.business_type, r.region_admin1,
       k.approved_allocation_cents, k.status AS kyc_status
  FROM core.needs_requests n
  JOIN core.recipients r ON r.id = n.recipient_id
  LEFT JOIN core.recipients_kyc k ON k.recipient_id = n.recipient_id;

CREATE OR REPLACE VIEW core.v_admin_reports AS
SELECT x.id, x.reason, x.details, x.status, x.created_at,
       c.slug AS campaign_slug, c.title AS campaign_title, c.status AS campaign_status, c.recipient_id,
       (SELECT count(*) FROM core.campaign_reports y WHERE y.campaign_id = x.campaign_id) AS reports_on_campaign
  FROM core.campaign_reports x
  JOIN core.campaigns c ON c.id = x.campaign_id;

-- ---- 5. public trust statistics (counts and sums only: no person is identifiable) ---------------------------------------------
CREATE OR REPLACE VIEW api.public_trust_stats AS
SELECT count(*) FILTER (WHERE status IN ('captured', 'paid_out'))                                    AS gifts_received,
       count(*) FILTER (WHERE status = 'paid_out')                                                    AS gifts_delivered,
       COALESCE(sum(amount_cents) FILTER (WHERE status IN ('captured', 'paid_out')), 0)              AS raised_cents,
       COALESCE(sum(net_cents)    FILTER (WHERE status = 'paid_out'), 0)                              AS delivered_cents,
       COALESCE(sum(net_cents)    FILTER (WHERE status = 'captured'), 0)                              AS awaiting_payout_cents,
       COALESCE(sum(platform_fee_cents) FILTER (WHERE status IN ('captured', 'paid_out')), 0)        AS platform_fees_cents,
       count(*) FILTER (WHERE status = 'refunded')                                                    AS refunds,
       (percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (paid_out_at - captured_at)))
            FILTER (WHERE status = 'paid_out' AND paid_out_at IS NOT NULL AND captured_at IS NOT NULL))::bigint
                                                                                                      AS median_payout_seconds
  FROM core.donations;

-- ---- 6. account: password -----------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.fn_get_my_password_hash()
RETURNS text
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT password_hash FROM core.users WHERE id = core.current_user_id() AND is_active $$;

CREATE OR REPLACE FUNCTION api.fn_set_my_password_hash(p_hash text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF core.current_user_id() IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE core.users SET password_hash = p_hash, failed_login_count = 0, locked_until = NULL
     WHERE id = core.current_user_id() AND is_active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'account not found' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    PERFORM core.fn_audit(core.current_user_id(), 'account.password_changed', 'users', core.current_user_id()::text);
END $$;

-- ---- 7. account: deletion --------------------------------------------------------------------------------------------------------
-- Why a "tombstone" and not DELETE: donations, ledger rows and audit rows must stay (append-only, restricted foreign keys),
-- so the person is erased from the row instead. Everything that identifies them is removed or scrambled; what remains
-- is an inactive shell that no one can sign in to and that names nobody.
CREATE OR REPLACE FUNCTION api.fn_delete_blockers()
RETURNS text[]
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
DECLARE
    v_uid  uuid := core.current_user_id();
    v_role core.user_role;
    v_rid  uuid;
    v_out  text[] := '{}';
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT role INTO v_role FROM core.users WHERE id = v_uid AND is_active;
    IF v_role IS NULL THEN
        RAISE EXCEPTION 'account not found' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF v_role NOT IN ('donor', 'recipient') THEN
        RETURN ARRAY['Staff accounts are removed by an administrator, not from settings.'];
    END IF;
    IF v_role = 'recipient' THEN
        SELECT id INTO v_rid FROM core.recipients WHERE user_id = v_uid;
        IF v_rid IS NOT NULL THEN
            IF EXISTS (SELECT 1 FROM core.donations WHERE recipient_id = v_rid AND status IN ('initiated', 'captured')) THEN
                v_out := array_append(v_out, 'A gift to you is still being processed. Wait until it has been paid out (or has expired), then try again.'::text);
            END IF;
            IF EXISTS (SELECT 1 FROM core.payout_queue WHERE recipient_id = v_rid
                        AND status IN ('queued', 'batched', 'submitted', 'held', 'unclaimed')) THEN
                v_out := array_append(v_out, 'A payout to you is still on its way (or unclaimed). Claim it or wait for it to settle, then try again.'::text);
            END IF;
        END IF;
    END IF;
    RETURN v_out;
END $$;

-- Returns the stored files that must now be erased, as 'vault:<key>' or 'public:<key>'.
CREATE OR REPLACE FUNCTION api.fn_delete_my_account()
RETURNS text[]
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE
    v_uid      uuid := core.current_user_id();
    v_role     core.user_role;
    v_rid      uuid;
    v_blockers text[];
    v_files    text[] := '{}';
    v_tmp      text[];
BEGIN
    v_blockers := api.fn_delete_blockers();           -- also checks authentication and that the account exists
    IF cardinality(v_blockers) > 0 THEN
        RAISE EXCEPTION '%', v_blockers[1] USING ERRCODE = 'check_violation';
    END IF;
    SELECT role INTO v_role FROM core.users WHERE id = v_uid;

    IF v_role = 'recipient' THEN
        SELECT id INTO v_rid FROM core.recipients WHERE user_id = v_uid;
        IF v_rid IS NOT NULL THEN
            -- Verification data: identity fields wiped, case suspended (the trigger closes campaigns and hides the profile).
            UPDATE core.recipients_kyc
               SET status = 'suspended', rejection_reason = 'Account deleted by the account holder',
                   full_name_enc = NULL, dob_enc = NULL, nic_number_enc = NULL, nic_blind_idx = NULL, address_enc = NULL,
                   doc_country = NULL, data_retention_until = now(), ai_fraud_flags = '[]'::jsonb
             WHERE recipient_id = v_rid;

            SELECT COALESCE(array_agg('vault:' || object_key), '{}') INTO v_tmp
              FROM core.kyc_documents WHERE recipient_id = v_rid AND deleted_at IS NULL;
            v_files := v_files || v_tmp;
            UPDATE core.kyc_documents SET deleted_at = now(), wrapped_dek = '\x'::bytea
             WHERE recipient_id = v_rid AND deleted_at IS NULL;

            SELECT COALESCE(array_agg('vault:' || proof_object_key), '{}') INTO v_tmp
              FROM core.needs_requests WHERE recipient_id = v_rid AND proof_object_key IS NOT NULL;
            v_files := v_files || v_tmp;
            UPDATE core.needs_requests
               SET proof_object_key = NULL, proof_wrapped_dek = NULL, proof_sha256 = NULL, proof_mime = NULL,
                   explanation = '', items = '[]'::jsonb || jsonb_build_object('name', '(removed)'), ai_result = '{}'::jsonb,
                   status = CASE WHEN status = 'submitted' THEN 'declined' ELSE status END
             WHERE recipient_id = v_rid;

            SELECT COALESCE(array_agg('public:' || k), '{}') INTO v_tmp
              FROM (SELECT cover_object_key AS k FROM core.campaigns WHERE recipient_id = v_rid AND cover_object_key IS NOT NULL
                    UNION ALL SELECT avatar_object_key FROM core.recipients WHERE id = v_rid AND avatar_object_key IS NOT NULL
                    UNION ALL SELECT unnest(u.media_object_keys) FROM core.campaign_updates u
                               JOIN core.campaigns c ON c.id = u.campaign_id WHERE c.recipient_id = v_rid) s
             WHERE k IS NOT NULL;
            v_files := v_files || v_tmp;
            UPDATE core.campaign_updates u SET body = '[removed]', media_object_keys = '{}'
              FROM core.campaigns c WHERE c.id = u.campaign_id AND c.recipient_id = v_rid;
            UPDATE core.campaigns SET status = 'closed', title = 'Closed campaign', story = '', cover_object_key = NULL
             WHERE recipient_id = v_rid;

            UPDATE core.recipients
               SET public_name = 'Former member', story = '', business_type = NULL, region_admin1 = NULL, avatar_object_key = NULL,
                   profile_public = false, consent_public_profile_at = NULL,
                   slug = 'former-' || substr(md5(id::text), 1, 12),
                   paypal_receiver_enc = sha256(convert_to(gen_random_uuid()::text, 'UTF8')),
                   paypal_receiver_blind_idx = sha256(convert_to(gen_random_uuid()::text, 'UTF8'))
             WHERE id = v_rid;
        END IF;
    END IF;

    -- Comments the person wrote (any role) are blanked and hidden.
    SELECT COALESCE(array_agg('public:' || media_object_key), '{}') INTO v_tmp
      FROM core.campaign_comments WHERE author_user_id = v_uid AND media_object_key IS NOT NULL;
    v_files := v_files || v_tmp;
    UPDATE core.campaign_comments SET body = '[removed]', media_object_key = NULL, moderation_status = 'rejected'
     WHERE author_user_id = v_uid;

    DELETE FROM core.donor_pledges WHERE user_id = v_uid;
    DELETE FROM core.leaderboard   WHERE user_id = v_uid;

    UPDATE core.users
       SET email_enc = sha256(convert_to(gen_random_uuid()::text, 'UTF8')),
           email_blind_idx = sha256(convert_to(gen_random_uuid()::text, 'UTF8')),
           phone_enc = NULL, phone_blind_idx = NULL, password_hash = '!deleted',
           display_name = NULL, country_code = NULL, email_verified_at = NULL, phone_verified_at = NULL,
           locked_until = NULL, is_active = false, deleted_at = now()
     WHERE id = v_uid;

    PERFORM core.fn_audit(v_uid, 'account.deleted', 'users', v_uid::text, jsonb_build_object('role', v_role));
    RETURN v_files;
END $$;

-- ---- 8. needs requests (recipient side) ------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.fn_needs_submit(
    p_country char, p_currency char, p_items jsonb, p_requested_total_cents bigint, p_estimated_total_cents bigint,
    p_explanation text, p_proof_key text, p_proof_wrapped_dek bytea, p_proof_mime text, p_proof_sha256 bytea,
    p_hr_status text, p_priority text, p_ai jsonb)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_uid uuid := core.current_user_id(); v_rid uuid; v_id uuid;
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT r.id INTO v_rid FROM core.recipients r JOIN core.users u ON u.id = r.user_id
     WHERE r.user_id = v_uid AND u.is_active AND u.role = 'recipient';
    IF v_rid IS NULL THEN
        RAISE EXCEPTION 'create your profile first' USING ERRCODE = 'check_violation';
    END IF;
    IF (SELECT count(*) FROM core.needs_requests WHERE recipient_id = v_rid AND created_at > now() - interval '1 day') >= 5 THEN
        RAISE EXCEPTION 'too many requests today' USING ERRCODE = 'program_limit_exceeded';
    END IF;
    IF EXISTS (SELECT 1 FROM core.needs_requests WHERE recipient_id = v_rid AND status = 'submitted' AND created_at > now() - interval '10 minutes'
                  AND items = p_items) THEN
        RAISE EXCEPTION 'this list was just submitted' USING ERRCODE = 'unique_violation';
    END IF;
    INSERT INTO core.needs_requests (recipient_id, country, local_currency, items, requested_total_cents, estimated_total_cents,
                                     explanation, proof_object_key, proof_wrapped_dek, proof_mime, proof_sha256,
                                     hr_filter_status, priority_queue, ai_result)
    VALUES (v_rid, upper(p_country), upper(p_currency), p_items, p_requested_total_cents, p_estimated_total_cents,
            COALESCE(p_explanation, ''), p_proof_key, p_proof_wrapped_dek, p_proof_mime, p_proof_sha256,
            p_hr_status, p_priority, COALESCE(p_ai, '{}'::jsonb))
    RETURNING id INTO v_id;
    PERFORM core.fn_audit(v_uid, 'needs.submitted', 'needs_requests', v_id::text);
    RETURN v_id;
END $$;

-- The recipient sees the outcome and the reviewer's note, not the internal fraud flags (so the checks cannot be coached around).
CREATE OR REPLACE FUNCTION api.fn_needs_list()
RETURNS TABLE (id uuid, status text, country char, local_currency char, items jsonb, requested_total_cents bigint,
               estimated_total_cents bigint, has_proof boolean, reviewer_note text, created_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT n.id, n.status, n.country, n.local_currency, n.items, n.requested_total_cents, n.estimated_total_cents,
             (n.proof_object_key IS NOT NULL), n.reviewer_note, n.created_at
        FROM core.needs_requests n JOIN core.recipients r ON r.id = n.recipient_id
       WHERE r.user_id = core.current_user_id()
       ORDER BY n.created_at DESC LIMIT 20 $$;

-- Staff: decide a request. The AI result is advisory only; this is the only place a status changes.
CREATE OR REPLACE FUNCTION core.fn_decide_needs(p_id uuid, p_decision text, p_note text, p_reviewer uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role;
BEGIN
    SELECT role INTO v_role FROM core.users WHERE id = p_reviewer AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('reviewer', 'admin') THEN
        RAISE EXCEPTION 'reviewer must be an active reviewer or admin' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_decision NOT IN ('approved', 'declined', 'more_info') THEN
        RAISE EXCEPTION 'decision must be approved, declined or more_info' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_decision <> 'approved' AND COALESCE(btrim(p_note), '') = '' THEN
        RAISE EXCEPTION 'give the recipient a short reason' USING ERRCODE = 'check_violation';
    END IF;
    UPDATE core.needs_requests
       SET status = p_decision, reviewer_id = p_reviewer, reviewed_at = now(), reviewer_note = left(p_note, 500)
     WHERE id = p_id AND status IN ('submitted', 'more_info');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no open request with that id' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    PERFORM core.fn_audit(p_reviewer, 'needs.' || p_decision, 'needs_requests', p_id::text);
END $$;

CREATE OR REPLACE FUNCTION core.fn_audit_needs_proof_view(p_actor uuid, p_id uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role;
BEGIN
    SELECT role INTO v_role FROM core.users WHERE id = p_actor AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('reviewer', 'admin') THEN
        RAISE EXCEPTION 'only active staff can view proof images' USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM core.fn_audit(p_actor, 'needs.proof_viewed', 'needs_requests', p_id::text);
END $$;

-- Staff read of the proof file reference (kept out of the queue view so keys are never listed).
CREATE OR REPLACE FUNCTION core.fn_needs_proof_ref(p_id uuid)
RETURNS TABLE (object_key text, wrapped_dek bytea, mime_type text)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT proof_object_key, proof_wrapped_dek, proof_mime FROM core.needs_requests
       WHERE id = p_id AND proof_object_key IS NOT NULL $$;

-- ---- 9. campaign reports ----------------------------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION api.fn_report_campaign(p_slug text, p_reason text, p_details text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_cid uuid; v_id uuid; v_uid uuid := core.current_user_id();
BEGIN
    SELECT c.id INTO v_cid FROM core.campaigns c WHERE c.slug = p_slug AND c.status IN ('active', 'funded');
    IF v_cid IS NULL THEN
        RAISE EXCEPTION 'campaign not found' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_reason NOT IN ('fake_or_misleading', 'not_in_need', 'impersonation', 'inappropriate', 'other') THEN
        RAISE EXCEPTION 'unknown reason' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF v_uid IS NOT NULL AND EXISTS (SELECT 1 FROM core.campaign_reports WHERE campaign_id = v_cid AND reporter_user_id = v_uid AND status = 'open') THEN
        RAISE EXCEPTION 'you have already reported this campaign' USING ERRCODE = 'unique_violation';
    END IF;
    INSERT INTO core.campaign_reports (campaign_id, reporter_user_id, reason, details)
    VALUES (v_cid, v_uid, p_reason, left(COALESCE(p_details, ''), 1000)) RETURNING id INTO v_id;
    RETURN v_id;
END $$;

CREATE OR REPLACE FUNCTION core.fn_resolve_report(p_id uuid, p_status text, p_reviewer uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role;
BEGIN
    SELECT role INTO v_role FROM core.users WHERE id = p_reviewer AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('reviewer', 'admin') THEN
        RAISE EXCEPTION 'reviewer must be an active reviewer or admin' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_status NOT IN ('dismissed', 'actioned') THEN
        RAISE EXCEPTION 'status must be dismissed or actioned' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    UPDATE core.campaign_reports SET status = p_status, reviewer_id = p_reviewer, reviewed_at = now()
     WHERE id = p_id AND status = 'open';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no open report with that id' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    PERFORM core.fn_audit(p_reviewer, 'report.' || p_status, 'campaign_reports', p_id::text);
END $$;

-- ---- 11. hardening: a signed-in cookie outlives account deletion (sessions are stateless JWTs), so refuse
--         public gifts from an account that is no longer active. Same signature and body as schema.sql plus one check.
CREATE OR REPLACE FUNCTION api.fn_create_donation(p_campaign_slug text, p_amount_cents bigint, p_is_anonymous boolean,
                                                  p_donor_user_id uuid, p_tracking_token_hash bytea)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_campaign uuid; v_recipient uuid; v_id uuid;
BEGIN
    IF p_is_anonymous THEN
        IF p_donor_user_id IS NOT NULL OR p_tracking_token_hash IS NULL THEN
            RAISE EXCEPTION 'anonymous donations take a token hash and no donor id' USING ERRCODE = 'check_violation';
        END IF;
    ELSE
        IF p_donor_user_id IS DISTINCT FROM core.current_user_id() THEN
            RAISE EXCEPTION 'donor id must match the authenticated user' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM core.users WHERE id = p_donor_user_id AND is_active) THEN
            RAISE EXCEPTION 'please sign in again' USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;

    SELECT id, recipient_id INTO v_campaign, v_recipient FROM core.campaigns WHERE slug = p_campaign_slug;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown campaign' USING ERRCODE = 'invalid_parameter_value';
    END IF;

    INSERT INTO core.donations (campaign_id, recipient_id, is_anonymous, donor_user_id, tracking_token_hash, amount_cents)
    VALUES (v_campaign, v_recipient, p_is_anonymous, p_donor_user_id, p_tracking_token_hash, p_amount_cents)
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- ---- 10. grants ----------------------------------------------------------------------------------------------------------------------------
GRANT SELECT ON api.public_trust_stats TO sadqah_api;
GRANT EXECUTE ON FUNCTION
    api.fn_get_my_password_hash(), api.fn_set_my_password_hash(text),
    api.fn_delete_blockers(), api.fn_delete_my_account(),
    api.fn_needs_submit(char, char, jsonb, bigint, bigint, text, text, bytea, text, bytea, text, text, jsonb),
    api.fn_needs_list(), api.fn_report_campaign(text, text, text)
    TO sadqah_api;
-- Postgres checks function privileges inside SECURITY DEFINER functions against the function owner, but a function
-- that calls another api.* function (fn_delete_my_account -> fn_delete_blockers) is fine because the owner may run both.

GRANT SELECT ON core.v_admin_needs_queue, core.v_admin_reports TO sadqah_admin;
GRANT EXECUTE ON FUNCTION
    core.fn_decide_needs(uuid, text, text, uuid), core.fn_audit_needs_proof_view(uuid, uuid),
    core.fn_needs_proof_ref(uuid), core.fn_resolve_report(uuid, text, uuid)
    TO sadqah_admin;

COMMIT;

RESET ROLE;
