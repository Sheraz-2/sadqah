-- =============================================================================
-- SadQah | database/schema.sql  (PostgreSQL 16)
--
-- Run AFTER roles.sql:   psql -v ON_ERROR_STOP=1 -d sadqah -f database/schema.sql
--
-- LAYOUT
--   schema core : every table and every internal function. Only sadqah_owner has
--                 table rights. Service roles get EXECUTE on specific functions,
--                 or SELECT on specific admin views, and nothing else.
--   schema api  : the ONLY surface the web API (sadqah_api) can touch. Masked views
--                 and SECURITY DEFINER functions. The API role has ZERO table rights.
--
-- PRIVACY GUARANTEES ENFORCED HERE (not just in application code)
--   1. Anonymous donations carry no donor id. CHECK constraint donations_anonymity_chk.
--   2. Identity columns of a donation are immutable, so nobody can "de-anonymise"
--      a row later with an UPDATE.
--   3. Tracking tokens are stored only as hashes. A leaked database cannot be used to
--      open anyone's tracking portal.
--   4. Messages carry no sender user id at all. A thread is keyed by donation, so the
--      recipient sees "A SadQah donor" and the donor sees only the public profile.
--   5. Public views never select donor_user_id or tracking_token_hash; timestamps of
--      anonymous gifts are truncated to the day to blunt timing correlation.
--   6. Payer identity (PayPal) lives in a separate table that no service role can read.
--   7. PII columns hold application-encrypted ciphertext (BYTEA); lookups use blind indexes.
--   8. The "< $50 / month" distress rule and "AI recommends, a human approves" rule
--      are CHECK constraints on recipients_kyc.
--
-- MONEY: all amounts are BIGINT minor units (cents). No floating point.
-- =============================================================================

SET ROLE sadqah_owner;

BEGIN;

CREATE SCHEMA core AUTHORIZATION sadqah_owner;
CREATE SCHEMA api  AUTHORIZATION sadqah_owner;
REVOKE ALL ON SCHEMA core, api FROM PUBLIC;

-- Functions are executable by PUBLIC by default in Postgres. Turn that off.
ALTER DEFAULT PRIVILEGES FOR ROLE sadqah_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Callers need to resolve api.* names; they get nothing in core.
GRANT USAGE ON SCHEMA api  TO sadqah_api;
GRANT USAGE ON SCHEMA core TO sadqah_worker, sadqah_webhook, sadqah_kyc, sadqah_admin;

-- =============================================================================
-- 1. ENUMS
-- =============================================================================
CREATE TYPE core.user_role          AS ENUM ('donor', 'recipient', 'reviewer', 'admin');
CREATE TYPE core.kyc_status         AS ENUM ('not_started', 'documents_pending', 'processing',
                                             'needs_human_review', 'approved', 'rejected', 'suspended');
CREATE TYPE core.kyc_doc_type       AS ENUM ('national_id', 'passport', 'utility_bill', 'selfie',
                                             'bank_statement', 'proof_of_income');
CREATE TYPE core.scan_status        AS ENUM ('pending', 'clean', 'infected', 'failed');
CREATE TYPE core.campaign_status    AS ENUM ('draft', 'active', 'funded', 'closed');
CREATE TYPE core.update_visibility  AS ENUM ('public', 'donors');
CREATE TYPE core.donation_status    AS ENUM ('initiated', 'captured', 'paid_out', 'refunded', 'failed', 'cancelled');
CREATE TYPE core.paypal_receiver_type AS ENUM ('EMAIL', 'PHONE', 'PAYPAL_ID');
CREATE TYPE core.payout_item_status AS ENUM ('queued', 'batched', 'submitted', 'succeeded', 'unclaimed',
                                             'returned', 'failed', 'blocked', 'held', 'cancelled');
CREATE TYPE core.batch_status       AS ENUM ('created', 'retry_wait', 'submitted', 'processing',
                                             'success', 'denied', 'failed');
CREATE TYPE core.ledger_event_type  AS ENUM ('donation_captured', 'donation_refunded', 'payout_queued',
                                             'payout_batched', 'payout_submitted', 'payout_succeeded',
                                             'payout_unclaimed', 'payout_returned', 'payout_failed',
                                             'payout_blocked', 'payout_held', 'payout_cancelled',
                                             'batch_submitted', 'batch_processing', 'batch_success',
                                             'batch_denied', 'batch_failed', 'adjustment');
CREATE TYPE core.message_sender     AS ENUM ('donor', 'recipient');
CREATE TYPE core.moderation_status  AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE core.webhook_status     AS ENUM ('received', 'processed', 'ignored', 'failed');
CREATE TYPE core.pledge_kind        AS ENUM ('percent_of_income', 'fixed_amount');
CREATE TYPE core.pledge_frequency   AS ENUM ('one_time', 'monthly', 'yearly');

-- =============================================================================
-- 2. HELPER FUNCTIONS
-- =============================================================================
-- The API sets this per request from the verified JWT:  SET LOCAL app.current_user_id = '<uuid>'
CREATE FUNCTION core.current_user_id() RETURNS uuid
LANGUAGE sql STABLE
AS $$ SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid $$;

CREATE FUNCTION core.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql
AS $$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$;

CREATE FUNCTION core.forbid_mutation() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed: table is append-only', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

-- Payout item state machine. Includes direct batched -> outcome edges because a PayPal
-- webhook can arrive before our own "submitted" commit.
CREATE FUNCTION core.payout_transition_allowed(o core.payout_item_status, n core.payout_item_status)
RETURNS boolean
LANGUAGE sql IMMUTABLE
AS $$
    SELECT o = n OR (o::text, n::text) IN (
        ('queued','batched'), ('queued','cancelled'),
        ('batched','queued'), ('batched','submitted'), ('batched','succeeded'), ('batched','unclaimed'),
        ('batched','failed'), ('batched','blocked'), ('batched','held'), ('batched','returned'),
        ('submitted','succeeded'), ('submitted','unclaimed'), ('submitted','failed'),
        ('submitted','blocked'), ('submitted','held'), ('submitted','returned'),
        ('held','succeeded'), ('held','failed'), ('held','blocked'), ('held','returned'),
        ('unclaimed','succeeded'), ('unclaimed','returned'),
        ('failed','queued'), ('blocked','queued')
    )
$$;

-- =============================================================================
-- 3. TABLES
-- =============================================================================

-- ---- users ------------------------------------------------------------------
CREATE TABLE core.users (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    role                core.user_role NOT NULL DEFAULT 'donor',
    email_enc           bytea NOT NULL,                       -- AES-256-GCM ciphertext
    email_blind_idx     bytea NOT NULL UNIQUE,                -- HMAC-SHA256(normalised email)
    phone_enc           bytea,
    phone_blind_idx     bytea UNIQUE,
    password_hash       text  NOT NULL,                       -- argon2id
    display_name        text,                                 -- PUBLIC handle, only shown for non-anonymous gifts
    country_code        char(2),
    email_verified_at   timestamptz,
    phone_verified_at   timestamptz,
    is_active           boolean NOT NULL DEFAULT true,
    failed_login_count  integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until        timestamptz,
    last_login_at       timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_display_name_len CHECK (display_name IS NULL OR char_length(display_name) BETWEEN 2 AND 40),
    CONSTRAINT users_country_upper    CHECK (country_code IS NULL OR country_code = upper(country_code)),
    CONSTRAINT users_phone_pair       CHECK ((phone_enc IS NULL) = (phone_blind_idx IS NULL))
);
CREATE TRIGGER trg_users_touch BEFORE UPDATE ON core.users
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

-- ---- recipients (profile) -----------------------------------------------------
CREATE TABLE core.recipients (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                  uuid NOT NULL UNIQUE REFERENCES core.users(id) ON DELETE RESTRICT,
    slug                     text NOT NULL UNIQUE,
    public_name              text NOT NULL,                   -- first name or chosen alias, never legal name
    story                    text NOT NULL DEFAULT '',
    business_type            text,
    region_country           char(2) NOT NULL,                -- coarse region only, by design
    region_admin1            text,                            -- province/state, never city or street
    avatar_object_key        text,
    paypal_receiver_type     core.paypal_receiver_type NOT NULL,
    paypal_receiver_enc      bytea NOT NULL,                  -- email / phone / PayPal id, encrypted
    paypal_receiver_blind_idx bytea NOT NULL UNIQUE,
    profile_public           boolean NOT NULL DEFAULT false,
    consent_public_profile_at timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT recipients_slug_fmt     CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) BETWEEN 3 AND 80),
    CONSTRAINT recipients_name_len     CHECK (char_length(public_name) BETWEEN 2 AND 60),
    CONSTRAINT recipients_story_len    CHECK (char_length(story) <= 5000),
    CONSTRAINT recipients_country_upper CHECK (region_country = upper(region_country)),
    CONSTRAINT recipients_public_needs_consent CHECK (NOT profile_public OR consent_public_profile_at IS NOT NULL)
);
CREATE TRIGGER trg_recipients_touch BEFORE UPDATE ON core.recipients
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();

-- ---- recipients_kyc -------------------------------------------------------------
CREATE TABLE core.recipients_kyc (
    id                              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id                    uuid NOT NULL UNIQUE REFERENCES core.recipients(id) ON DELETE RESTRICT,
    status                          core.kyc_status NOT NULL DEFAULT 'not_started',
    -- Identity data, encrypted by the application before it reaches the database
    full_name_enc                   bytea,
    dob_enc                         bytea,
    nic_number_enc                  bytea,
    nic_blind_idx                   bytea UNIQUE,             -- one identity = one recipient (duplicate-fraud guard)
    address_enc                     bytea,
    doc_country                     char(2),
    -- Consents (biometrics need explicit consent)
    consent_biometric_at            timestamptz,
    consent_data_at                 timestamptz,
    data_retention_until            timestamptz,
    -- AI assessment (advisory only)
    ai_extracted_monthly_income_cents bigint CHECK (ai_extracted_monthly_income_cents >= 0),
    ai_face_match_score             numeric(4,3) CHECK (ai_face_match_score BETWEEN 0 AND 1),
    ai_fraud_risk_score             numeric(4,3) CHECK (ai_fraud_risk_score BETWEEN 0 AND 1),
    ai_fraud_flags                  jsonb NOT NULL DEFAULT '[]'::jsonb,
    ai_recommended_allocation_cents bigint CHECK (ai_recommended_allocation_cents >= 0),
    ai_model_version                text,
    ai_assessed_at                  timestamptz,
    -- Human decision
    verified_monthly_income_cents   bigint CHECK (verified_monthly_income_cents >= 0),
    approved_allocation_cents       bigint CHECK (approved_allocation_cents >= 0),
    reviewer_id                     uuid REFERENCES core.users(id),
    reviewed_at                     timestamptz,
    rejection_reason                text,
    created_at                      timestamptz NOT NULL DEFAULT now(),
    updated_at                      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT kyc_flags_is_array CHECK (jsonb_typeof(ai_fraud_flags) = 'array'),
    -- Hard gate. 'approved' is impossible unless every one of these is true.
    -- 5000 cents = the platform's "< $50 per month" distress threshold.
    CONSTRAINT kyc_approved_requirements CHECK (
        status <> 'approved' OR (
            verified_monthly_income_cents IS NOT NULL
            AND verified_monthly_income_cents < 5000
            AND approved_allocation_cents IS NOT NULL
            AND reviewer_id IS NOT NULL
            AND reviewed_at IS NOT NULL
            AND ai_assessed_at IS NOT NULL
            AND ai_fraud_risk_score IS NOT NULL
            AND nic_blind_idx IS NOT NULL
            AND consent_biometric_at IS NOT NULL
            AND consent_data_at IS NOT NULL
        )
    ),
    CONSTRAINT kyc_rejected_needs_reason CHECK (status <> 'rejected' OR rejection_reason IS NOT NULL)
);
CREATE TRIGGER trg_kyc_touch BEFORE UPDATE ON core.recipients_kyc
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();
CREATE INDEX idx_kyc_status ON core.recipients_kyc (status);

-- ---- kyc_documents (metadata only; file bytes live encrypted in object storage) --
CREATE TABLE core.kyc_documents (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id    uuid NOT NULL REFERENCES core.recipients(id) ON DELETE RESTRICT,
    doc_type        core.kyc_doc_type NOT NULL,
    object_key      text  NOT NULL UNIQUE,                    -- random key, reveals nothing
    sha256          bytea NOT NULL CHECK (octet_length(sha256) = 32),
    mime_type       text  NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'application/pdf')),
    size_bytes      bigint NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 15 * 1024 * 1024),
    wrapped_dek     bytea NOT NULL,                           -- per-file data key, wrapped by master key
    scan_status     core.scan_status NOT NULL DEFAULT 'pending',
    uploaded_at     timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);
CREATE INDEX idx_kyc_docs_recipient ON core.kyc_documents (recipient_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_kyc_one_selfie  ON core.kyc_documents (recipient_id) WHERE doc_type = 'selfie' AND deleted_at IS NULL;

-- ---- campaigns ----------------------------------------------------------------
CREATE TABLE core.campaigns (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id    uuid NOT NULL REFERENCES core.recipients(id) ON DELETE RESTRICT,
    slug            text NOT NULL UNIQUE,
    title           text NOT NULL,
    story           text NOT NULL DEFAULT '',
    cover_object_key text,
    currency        char(3) NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    goal_cents      bigint NOT NULL CHECK (goal_cents > 0),
    raised_cents    bigint NOT NULL DEFAULT 0 CHECK (raised_cents >= 0),     -- captured, gross
    paid_out_cents  bigint NOT NULL DEFAULT 0 CHECK (paid_out_cents >= 0),   -- confirmed delivered, net
    status          core.campaign_status NOT NULL DEFAULT 'draft',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, recipient_id),
    CONSTRAINT campaigns_slug_fmt  CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) BETWEEN 3 AND 80),
    CONSTRAINT campaigns_title_len CHECK (char_length(title) BETWEEN 3 AND 120),
    CONSTRAINT campaigns_story_len CHECK (char_length(story) <= 8000)
);
CREATE TRIGGER trg_campaigns_touch BEFORE UPDATE ON core.campaigns
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();
-- One live campaign per recipient: prevents splitting one person's need into many asks.
CREATE UNIQUE INDEX uq_one_open_campaign ON core.campaigns (recipient_id) WHERE status IN ('draft', 'active');

CREATE TABLE core.campaign_updates (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     uuid NOT NULL REFERENCES core.campaigns(id) ON DELETE RESTRICT,
    body            text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
    media_object_keys text[] NOT NULL DEFAULT '{}' CHECK (cardinality(media_object_keys) <= 6),
    visibility      core.update_visibility NOT NULL DEFAULT 'public',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_updates_campaign ON core.campaign_updates (campaign_id, created_at DESC);

CREATE TABLE core.campaign_comments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     uuid NOT NULL REFERENCES core.campaigns(id) ON DELETE RESTRICT,
    author_user_id  uuid NOT NULL REFERENCES core.users(id) ON DELETE RESTRICT,
    body            text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
    media_object_key text,
    moderation_status core.moderation_status NOT NULL DEFAULT 'pending',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_comments_campaign ON core.campaign_comments (campaign_id, created_at DESC)
    WHERE moderation_status = 'approved';

-- ---- donations -------------------------------------------------------------------
-- The row id IS the transaction UUID. It exists, bound to a recipient, before PayPal is called.
CREATE TABLE core.donations (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id         uuid NOT NULL,
    recipient_id        uuid NOT NULL,
    is_anonymous        boolean NOT NULL,
    donor_user_id       uuid REFERENCES core.users(id) ON DELETE RESTRICT,
    tracking_token_hash bytea UNIQUE CHECK (tracking_token_hash IS NULL OR octet_length(tracking_token_hash) = 32),
    amount_cents        bigint NOT NULL CHECK (amount_cents BETWEEN 100 AND 500000),   -- $1 to $5,000
    platform_fee_cents  bigint NOT NULL DEFAULT 0 CHECK (platform_fee_cents >= 0),
    net_cents           bigint GENERATED ALWAYS AS (amount_cents - platform_fee_cents) STORED,
    currency            char(3) NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    status              core.donation_status NOT NULL DEFAULT 'initiated',
    paypal_order_id     text UNIQUE,
    paypal_capture_id   text UNIQUE,
    created_at          timestamptz NOT NULL DEFAULT now(),
    captured_at         timestamptz,
    paid_out_at         timestamptz,
    FOREIGN KEY (campaign_id, recipient_id) REFERENCES core.campaigns (id, recipient_id) ON DELETE RESTRICT,
    CONSTRAINT donations_fee_lt_amount CHECK (platform_fee_cents < amount_cents),
    -- THE anonymity guarantee: anonymous rows have no donor id and must have a token;
    -- public rows must have a donor id.
    CONSTRAINT donations_anonymity_chk CHECK (
        (is_anonymous     AND donor_user_id IS NULL     AND tracking_token_hash IS NOT NULL) OR
        (NOT is_anonymous AND donor_user_id IS NOT NULL)
    ),
    CONSTRAINT donations_capture_ref CHECK (status NOT IN ('captured', 'paid_out') OR paypal_capture_id IS NOT NULL)
);
CREATE INDEX idx_donations_donor     ON core.donations (donor_user_id) WHERE donor_user_id IS NOT NULL;
CREATE INDEX idx_donations_recipient ON core.donations (recipient_id, status);
CREATE INDEX idx_donations_campaign  ON core.donations (campaign_id, created_at DESC);
CREATE INDEX idx_donations_stale     ON core.donations (created_at) WHERE status = 'initiated';

-- PayPal payer reference, encrypted, separated so no service role can join it to anything.
CREATE TABLE core.donation_payer_private (
    donation_id     uuid PRIMARY KEY REFERENCES core.donations(id) ON DELETE RESTRICT,
    payer_ref_enc   bytea,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ---- payout batches & queue -------------------------------------------------------
CREATE TABLE core.payout_batches (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_batch_id         text NOT NULL UNIQUE,            -- idempotency key sent to PayPal, stored BEFORE the call
    paypal_payout_batch_id  text UNIQUE,
    status                  core.batch_status NOT NULL DEFAULT 'created',
    item_count              integer NOT NULL CHECK (item_count >= 0),
    total_cents             bigint  NOT NULL CHECK (total_cents >= 0),
    attempt_count           integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at         timestamptz NOT NULL DEFAULT now() + interval '2 minutes',  -- doubles as crash lease
    last_error              text CHECK (last_error IS NULL OR char_length(last_error) <= 500),
    created_at              timestamptz NOT NULL DEFAULT now(),
    submitted_at            timestamptz,
    completed_at            timestamptz,
    updated_at              timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_batches_touch BEFORE UPDATE ON core.payout_batches
    FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at();
CREATE INDEX idx_batches_due ON core.payout_batches (next_attempt_at) WHERE status IN ('created', 'retry_wait');
CREATE INDEX idx_batches_open ON core.payout_batches (submitted_at) WHERE status IN ('submitted', 'processing');

CREATE TABLE core.payout_queue (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    donation_id             uuid NOT NULL UNIQUE REFERENCES core.donations(id) ON DELETE RESTRICT,
    recipient_id            uuid NOT NULL REFERENCES core.recipients(id) ON DELETE RESTRICT,
    amount_cents            bigint NOT NULL CHECK (amount_cents > 0),
    currency                char(3) NOT NULL DEFAULT 'USD',
    status                  core.payout_item_status NOT NULL DEFAULT 'queued',
    batch_id                uuid REFERENCES core.payout_batches(id) ON DELETE RESTRICT,
    -- The donation UUID travels to PayPal as sender_item_id: exact 1:1 reconciliation key.
    sender_item_id          text GENERATED ALWAYS AS (donation_id::text) STORED,
    paypal_payout_item_id   text UNIQUE,
    paypal_transaction_status text,
    failure_reason          text CHECK (failure_reason IS NULL OR char_length(failure_reason) <= 300),
    last_event_id           text,
    next_attempt_at         timestamptz NOT NULL DEFAULT now(),
    queued_at               timestamptz NOT NULL DEFAULT now(),
    batched_at              timestamptz,
    submitted_at            timestamptz,
    settled_at              timestamptz,
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT payout_batch_required CHECK (status IN ('queued', 'cancelled', 'failed', 'blocked') OR batch_id IS NOT NULL)
);
CREATE UNIQUE INDEX uq_payout_sender_item ON core.payout_queue (sender_item_id);
CREATE INDEX idx_payout_claimable ON core.payout_queue (queued_at) WHERE status = 'queued';
CREATE INDEX idx_payout_batch     ON core.payout_queue (batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX idx_payout_recipient ON core.payout_queue (recipient_id, status);

-- ---- ledger (append-only) -----------------------------------------------------------
CREATE TABLE core.ledger_events (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type          core.ledger_event_type NOT NULL,
    donation_id         uuid REFERENCES core.donations(id),
    payout_queue_id     uuid REFERENCES core.payout_queue(id),
    batch_id            uuid REFERENCES core.payout_batches(id),
    recipient_id        uuid REFERENCES core.recipients(id),
    amount_cents        bigint CHECK (amount_cents >= 0),
    currency            char(3) NOT NULL DEFAULT 'USD',
    source              text NOT NULL DEFAULT 'db' CHECK (source IN ('api', 'worker', 'webhook', 'reconciler', 'admin', 'db')),
    external_event_id   text,                                   -- PayPal event id when applicable
    details             jsonb NOT NULL DEFAULT '{}'::jsonb,     -- never contains donor identity or contact data
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_ledger_donation  ON core.ledger_events (donation_id, id);
CREATE INDEX idx_ledger_recipient ON core.ledger_events (recipient_id, id);
CREATE INDEX idx_ledger_batch     ON core.ledger_events (batch_id, id) WHERE batch_id IS NOT NULL;
CREATE TRIGGER trg_ledger_no_row_mutation BEFORE UPDATE OR DELETE ON core.ledger_events
    FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();
CREATE TRIGGER trg_ledger_no_truncate BEFORE TRUNCATE ON core.ledger_events
    FOR EACH STATEMENT EXECUTE FUNCTION core.forbid_mutation();

CREATE TABLE core.audit_log (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id   uuid,
    action          text NOT NULL,
    entity_type     text NOT NULL,
    entity_id       text,
    details         jsonb NOT NULL DEFAULT '{}'::jsonb,         -- keep free of donor/recipient PII
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_audit_no_row_mutation BEFORE UPDATE OR DELETE ON core.audit_log
    FOR EACH ROW EXECUTE FUNCTION core.forbid_mutation();
CREATE TRIGGER trg_audit_no_truncate BEFORE TRUNCATE ON core.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION core.forbid_mutation();

-- ---- webhook inbox (idempotency) ----------------------------------------------------
CREATE TABLE core.webhook_events (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    paypal_event_id text NOT NULL UNIQUE,                       -- replays collide here and become no-ops
    event_type      text NOT NULL,
    resource_id     text,
    payload         jsonb NOT NULL,                             -- scrubbed of payer/receiver data on the way in
    status          core.webhook_status NOT NULL DEFAULT 'received',
    error           text CHECK (error IS NULL OR char_length(error) <= 500),
    received_at     timestamptz NOT NULL DEFAULT now(),
    processed_at    timestamptz
);
CREATE INDEX idx_webhook_pending ON core.webhook_events (received_at) WHERE status IN ('received', 'failed');

-- ---- leaderboard (public donors only) -------------------------------------------------
CREATE TABLE core.leaderboard (
    user_id             uuid PRIMARY KEY REFERENCES core.users(id) ON DELETE RESTRICT,
    points              bigint NOT NULL DEFAULT 0 CHECK (points >= 0),
    total_donated_cents bigint NOT NULL DEFAULT 0 CHECK (total_donated_cents >= 0),
    donation_count      integer NOT NULL DEFAULT 0 CHECK (donation_count >= 0),
    show_publicly       boolean NOT NULL DEFAULT true,
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_leaderboard_points ON core.leaderboard (points DESC) WHERE show_publicly;

-- ---- anonymous messaging ----------------------------------------------------------------
-- Deliberately NO user id column. A message belongs to a donation thread, never to a person.
CREATE TABLE core.anonymous_messages (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    donation_id             uuid NOT NULL REFERENCES core.donations(id) ON DELETE RESTRICT,
    sender                  core.message_sender NOT NULL,
    body_enc                bytea NOT NULL CHECK (octet_length(body_enc) BETWEEN 29 AND 8192),
    moderation_status       core.moderation_status NOT NULL DEFAULT 'pending',
    moderation_reason       text CHECK (moderation_reason IS NULL OR char_length(moderation_reason) <= 300),
    moderated_at            timestamptz,
    read_by_donor_at        timestamptz,
    read_by_recipient_at    timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_thread  ON core.anonymous_messages (donation_id, created_at);
CREATE INDEX idx_messages_pending ON core.anonymous_messages (created_at) WHERE moderation_status = 'pending';

-- ---- gratitude ------------------------------------------------------------------------------
CREATE TABLE core.gratitude_notes (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    donation_id         uuid NOT NULL UNIQUE REFERENCES core.donations(id) ON DELETE RESTRICT,
    recipient_id        uuid NOT NULL REFERENCES core.recipients(id) ON DELETE RESTRICT,
    to_user_id          uuid REFERENCES core.users(id) ON DELETE RESTRICT,   -- set only for public donors
    is_community        boolean NOT NULL,
    body                text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 1000),
    moderation_status   core.moderation_status NOT NULL DEFAULT 'pending',
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT gratitude_target_chk CHECK (is_community = (to_user_id IS NULL))
);
CREATE INDEX idx_gratitude_public ON core.gratitude_notes (created_at DESC) WHERE moderation_status = 'approved';

-- ---- donor pledges (the 1% to 5% giving plan; income itself is NEVER stored) ---------------------
CREATE TABLE core.donor_pledges (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL REFERENCES core.users(id) ON DELETE RESTRICT,
    kind                core.pledge_kind NOT NULL,
    percent             numeric(4,2),
    amount_cents        bigint NOT NULL CHECK (amount_cents >= 100 AND amount_cents <= 500000),
    frequency           core.pledge_frequency NOT NULL,
    default_anonymous   boolean NOT NULL DEFAULT false,
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pledge_percent_chk CHECK (
        (kind = 'percent_of_income' AND percent BETWEEN 1 AND 5) OR
        (kind = 'fixed_amount'      AND percent IS NULL)
    )
);
CREATE UNIQUE INDEX uq_one_active_pledge ON core.donor_pledges (user_id) WHERE active;

-- =============================================================================
-- 4. INTEGRITY TRIGGERS (all SECURITY DEFINER so callers need no table rights)
-- =============================================================================

-- ---- recipients: public profile only for approved KYC -----------------------------------------
CREATE FUNCTION core.trg_recipients_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF NEW.profile_public AND NOT EXISTS (
        SELECT 1 FROM core.recipients_kyc k WHERE k.recipient_id = NEW.id AND k.status = 'approved') THEN
        RAISE EXCEPTION 'profile cannot be public before KYC approval' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_recipients_guard BEFORE UPDATE OF profile_public ON core.recipients
    FOR EACH ROW WHEN (NEW.profile_public) EXECUTE FUNCTION core.trg_recipients_guard();

-- ---- KYC: reviewer independence + suspend cascades ------------------------------------------------
CREATE FUNCTION core.trg_kyc_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF NEW.status = 'approved' AND EXISTS (
        SELECT 1 FROM core.recipients r WHERE r.id = NEW.recipient_id AND r.user_id = NEW.reviewer_id) THEN
        RAISE EXCEPTION 'a recipient cannot review their own KYC' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_kyc_guard BEFORE INSERT OR UPDATE ON core.recipients_kyc
    FOR EACH ROW EXECUTE FUNCTION core.trg_kyc_guard();

CREATE FUNCTION core.trg_kyc_after_status() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF NEW.status IN ('rejected', 'suspended') THEN
        UPDATE core.campaigns SET status = 'closed'
         WHERE recipient_id = NEW.recipient_id AND status IN ('draft', 'active');
        UPDATE core.recipients SET profile_public = false WHERE id = NEW.recipient_id AND profile_public;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_kyc_after_status AFTER UPDATE OF status ON core.recipients_kyc
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status) EXECUTE FUNCTION core.trg_kyc_after_status();

-- ---- campaigns: active needs approved KYC; goal capped by approved allocation ------------------------
CREATE FUNCTION core.trg_campaigns_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE
    v_kyc core.kyc_status;
    v_alloc bigint;
BEGIN
    IF NEW.status IN ('active', 'funded') OR TG_OP = 'INSERT' THEN
        SELECT status, approved_allocation_cents INTO v_kyc, v_alloc
          FROM core.recipients_kyc WHERE recipient_id = NEW.recipient_id;
        IF v_kyc IS DISTINCT FROM 'approved' THEN
            RAISE EXCEPTION 'campaigns require an approved KYC' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.goal_cents > v_alloc THEN
            RAISE EXCEPTION 'campaign goal exceeds the approved allocation' USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_campaigns_guard BEFORE INSERT OR UPDATE OF status, goal_cents ON core.campaigns
    FOR EACH ROW EXECUTE FUNCTION core.trg_campaigns_guard();

-- ---- donations: validate on insert --------------------------------------------------------------------
CREATE FUNCTION core.trg_donations_before_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE
    v_cstatus core.campaign_status;
    v_kyc     core.kyc_status;
BEGIN
    SELECT c.status, k.status INTO v_cstatus, v_kyc
      FROM core.campaigns c
      JOIN core.recipients_kyc k ON k.recipient_id = c.recipient_id
     WHERE c.id = NEW.campaign_id AND c.recipient_id = NEW.recipient_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'campaign/recipient mismatch' USING ERRCODE = 'check_violation';
    END IF;
    IF v_cstatus <> 'active' THEN
        RAISE EXCEPTION 'campaign is not accepting donations' USING ERRCODE = 'check_violation';
    END IF;
    IF v_kyc <> 'approved' THEN
        RAISE EXCEPTION 'recipient is not verified' USING ERRCODE = 'check_violation';
    END IF;
    NEW.status := 'initiated';
    NEW.captured_at := NULL;
    NEW.paid_out_at := NULL;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_donations_before_insert BEFORE INSERT ON core.donations
    FOR EACH ROW EXECUTE FUNCTION core.trg_donations_before_insert();

-- ---- donations: identity is immutable, status machine enforced ------------------------------------------
CREATE FUNCTION core.trg_donations_guard_update() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF NEW.id                  IS DISTINCT FROM OLD.id
    OR NEW.campaign_id         IS DISTINCT FROM OLD.campaign_id
    OR NEW.recipient_id        IS DISTINCT FROM OLD.recipient_id
    OR NEW.is_anonymous        IS DISTINCT FROM OLD.is_anonymous
    OR NEW.donor_user_id       IS DISTINCT FROM OLD.donor_user_id
    OR NEW.tracking_token_hash IS DISTINCT FROM OLD.tracking_token_hash
    OR NEW.amount_cents        IS DISTINCT FROM OLD.amount_cents
    OR NEW.platform_fee_cents  IS DISTINCT FROM OLD.platform_fee_cents
    OR NEW.currency            IS DISTINCT FROM OLD.currency
    OR NEW.created_at          IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'donation identity and amount columns are immutable' USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF (OLD.status::text, NEW.status::text) NOT IN (
            ('initiated','captured'), ('initiated','cancelled'), ('initiated','failed'),
            ('captured','paid_out'), ('captured','refunded')) THEN
            RAISE EXCEPTION 'illegal donation transition % -> %', OLD.status, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.status = 'captured'  THEN NEW.captured_at := now(); END IF;
        IF NEW.status = 'paid_out'  THEN NEW.paid_out_at := now(); END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_donations_guard_update BEFORE UPDATE ON core.donations
    FOR EACH ROW EXECUTE FUNCTION core.trg_donations_guard_update();

-- ---- donations: on capture, enqueue payout + ledger + totals + leaderboard in ONE transaction ------------------
CREATE FUNCTION core.trg_donations_after_captured() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    INSERT INTO core.payout_queue (donation_id, recipient_id, amount_cents, currency)
    VALUES (NEW.id, NEW.recipient_id, NEW.net_cents, NEW.currency)
    ON CONFLICT (donation_id) DO NOTHING;

    INSERT INTO core.ledger_events (event_type, donation_id, recipient_id, amount_cents, currency, details)
    VALUES ('donation_captured', NEW.id, NEW.recipient_id, NEW.amount_cents, NEW.currency,
            jsonb_build_object('campaign_id', NEW.campaign_id, 'fee_cents', NEW.platform_fee_cents));

    UPDATE core.campaigns
       SET raised_cents = raised_cents + NEW.amount_cents,
           status = CASE WHEN status = 'active' AND raised_cents + NEW.amount_cents >= goal_cents
                         THEN 'funded'::core.campaign_status ELSE status END
     WHERE id = NEW.campaign_id;

    IF NOT NEW.is_anonymous THEN
        INSERT INTO core.leaderboard (user_id, points, total_donated_cents, donation_count)
        VALUES (NEW.donor_user_id, GREATEST(1, NEW.amount_cents / 100), NEW.amount_cents, 1)
        ON CONFLICT (user_id) DO UPDATE
           SET points              = core.leaderboard.points + EXCLUDED.points,
               total_donated_cents = core.leaderboard.total_donated_cents + EXCLUDED.total_donated_cents,
               donation_count      = core.leaderboard.donation_count + 1,
               updated_at          = now();
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_donations_after_captured AFTER UPDATE OF status ON core.donations
    FOR EACH ROW WHEN (OLD.status = 'initiated' AND NEW.status = 'captured')
    EXECUTE FUNCTION core.trg_donations_after_captured();

-- ---- donations: refund is only possible while the payout is still queued ---------------------------------------
CREATE FUNCTION core.trg_donations_after_refund() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_cancelled integer;
BEGIN
    UPDATE core.payout_queue SET status = 'cancelled' WHERE donation_id = NEW.id AND status = 'queued';
    GET DIAGNOSTICS v_cancelled = ROW_COUNT;
    IF v_cancelled = 0 THEN
        RAISE EXCEPTION 'cannot refund: payout already left the queue' USING ERRCODE = 'check_violation';
    END IF;

    INSERT INTO core.ledger_events (event_type, donation_id, recipient_id, amount_cents, currency)
    VALUES ('donation_refunded', NEW.id, NEW.recipient_id, NEW.amount_cents, NEW.currency);

    UPDATE core.campaigns SET raised_cents = GREATEST(0, raised_cents - NEW.amount_cents) WHERE id = NEW.campaign_id;

    IF NOT NEW.is_anonymous THEN
        UPDATE core.leaderboard
           SET points = GREATEST(0, points - GREATEST(1, NEW.amount_cents / 100)),
               total_donated_cents = GREATEST(0, total_donated_cents - NEW.amount_cents),
               donation_count = GREATEST(0, donation_count - 1),
               updated_at = now()
         WHERE user_id = NEW.donor_user_id;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_donations_after_refund AFTER UPDATE OF status ON core.donations
    FOR EACH ROW WHEN (OLD.status = 'captured' AND NEW.status = 'refunded')
    EXECUTE FUNCTION core.trg_donations_after_refund();

-- ---- payout_queue: state machine, immutability, timestamps --------------------------------------------------------
CREATE FUNCTION core.trg_payout_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF NEW.donation_id  IS DISTINCT FROM OLD.donation_id
    OR NEW.recipient_id IS DISTINCT FROM OLD.recipient_id
    OR NEW.amount_cents IS DISTINCT FROM OLD.amount_cents
    OR NEW.currency     IS DISTINCT FROM OLD.currency THEN
        RAISE EXCEPTION 'payout identity and amount columns are immutable' USING ERRCODE = 'check_violation';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT core.payout_transition_allowed(OLD.status, NEW.status) THEN
            RAISE EXCEPTION 'illegal payout transition % -> %', OLD.status, NEW.status
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.status = 'batched'   THEN NEW.batched_at := now(); END IF;
        IF NEW.status = 'submitted' THEN NEW.submitted_at := now(); END IF;
        IF NEW.status IN ('succeeded', 'returned', 'failed', 'blocked', 'cancelled') THEN NEW.settled_at := now(); END IF;
        IF NEW.status = 'queued' THEN
            NEW.batch_id := NULL;
            NEW.batched_at := NULL;
            NEW.submitted_at := NULL;
            NEW.settled_at := NULL;
            NEW.failure_reason := NULL;
            NEW.next_attempt_at := now();
        END IF;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;
CREATE TRIGGER trg_payout_guard BEFORE UPDATE ON core.payout_queue
    FOR EACH ROW EXECUTE FUNCTION core.trg_payout_guard();

-- ---- payout_queue: every change becomes a ledger event; success opens the donor/recipient thread ----------------------
CREATE FUNCTION core.trg_payout_after_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO core.ledger_events (event_type, donation_id, payout_queue_id, recipient_id, amount_cents, currency)
        VALUES ('payout_queued', NEW.donation_id, NEW.id, NEW.recipient_id, NEW.amount_cents, NEW.currency);
        RETURN NEW;
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO core.ledger_events (event_type, donation_id, payout_queue_id, batch_id, recipient_id,
                                        amount_cents, currency, external_event_id, details)
        VALUES (('payout_' || NEW.status::text)::core.ledger_event_type, NEW.donation_id, NEW.id, NEW.batch_id,
                NEW.recipient_id, NEW.amount_cents, NEW.currency, NEW.last_event_id,
                jsonb_build_object('from', OLD.status, 'to', NEW.status, 'paypal_status', NEW.paypal_transaction_status));

        IF NEW.status = 'succeeded' THEN
            -- Real-time reconciliation: delivered money updates the donation (which opens the
            -- messaging thread and tracking state) and the campaign totals, in the same transaction.
            UPDATE core.donations SET status = 'paid_out' WHERE id = NEW.donation_id AND status = 'captured';
            UPDATE core.campaigns c SET paid_out_cents = c.paid_out_cents + NEW.amount_cents
              FROM core.donations d WHERE d.id = NEW.donation_id AND c.id = d.campaign_id;
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_payout_after_change AFTER INSERT OR UPDATE ON core.payout_queue
    FOR EACH ROW EXECUTE FUNCTION core.trg_payout_after_change();

-- ---- messages: only on delivered gifts, no cross-donation leakage ----------------------------------------------------------
CREATE FUNCTION core.trg_messages_before_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_status core.donation_status;
BEGIN
    SELECT status INTO v_status FROM core.donations WHERE id = NEW.donation_id;
    IF v_status IS DISTINCT FROM 'paid_out' THEN
        RAISE EXCEPTION 'messaging opens once the gift has been delivered' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_messages_before_insert BEFORE INSERT ON core.anonymous_messages
    FOR EACH ROW EXECUTE FUNCTION core.trg_messages_before_insert();

-- ---- gratitude: the target is derived from the donation, never supplied by the recipient -------------------------------------
CREATE FUNCTION core.trg_gratitude_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE d core.donations%ROWTYPE;
BEGIN
    SELECT * INTO d FROM core.donations WHERE id = NEW.donation_id;
    IF NOT FOUND OR d.recipient_id <> NEW.recipient_id OR d.status <> 'paid_out' THEN
        RAISE EXCEPTION 'gratitude requires a delivered donation to this recipient' USING ERRCODE = 'check_violation';
    END IF;
    IF d.is_anonymous THEN
        IF NEW.to_user_id IS NOT NULL THEN
            RAISE EXCEPTION 'anonymous donors can only be thanked as part of the community' USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.to_user_id IS DISTINCT FROM d.donor_user_id THEN
        RAISE EXCEPTION 'direct thanks must target the public donor of this gift' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_gratitude_guard BEFORE INSERT ON core.gratitude_notes
    FOR EACH ROW EXECUTE FUNCTION core.trg_gratitude_guard();

-- =============================================================================
-- 5. ROW LEVEL SECURITY (defence in depth)
--    Enabled everywhere. With no permissive policy, any role other than the owner is denied
--    even if someone later runs a careless GRANT. SECURITY DEFINER functions run as the owner
--    (table owner bypasses RLS because FORCE is not set), so the API keeps working.
-- =============================================================================
ALTER TABLE core.users                   ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.recipients              ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.recipients_kyc          ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.kyc_documents           ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.campaigns               ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.campaign_updates        ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.campaign_comments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.donations               ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.donation_payer_private  ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.payout_batches          ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.payout_queue            ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.ledger_events           ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.audit_log               ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.webhook_events          ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.leaderboard             ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.anonymous_messages      ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.gratitude_notes         ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.donor_pledges           ENABLE ROW LEVEL SECURITY;

-- The only direct reads granted at all: KYC pipeline and staff read KYC records (ciphertext).
CREATE POLICY kyc_read_pipeline_and_staff ON core.recipients_kyc
    FOR SELECT TO sadqah_kyc, sadqah_admin USING (true);
CREATE POLICY kycdocs_read_pipeline_and_staff ON core.kyc_documents
    FOR SELECT TO sadqah_kyc, sadqah_admin USING (true);

-- Belt and braces: nothing can ever UPDATE/DELETE ledger or audit rows, even as owner via SQL grants.
REVOKE UPDATE, DELETE, TRUNCATE ON core.ledger_events, core.audit_log FROM PUBLIC;

-- =============================================================================
-- 6. INTERNAL FUNCTIONS used by the worker, webhook handler, KYC pipeline and staff
-- =============================================================================

CREATE FUNCTION core.fn_audit(p_actor uuid, p_action text, p_entity_type text, p_entity_id text, p_details jsonb DEFAULT '{}'::jsonb)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$ INSERT INTO core.audit_log (actor_user_id, action, entity_type, entity_id, details)
      VALUES (p_actor, p_action, p_entity_type, p_entity_id, COALESCE(p_details, '{}'::jsonb)) $$;

-- ---- webhook inbox ---------------------------------------------------------------------------------------------
-- Returns TRUE if this PayPal event id is new, FALSE if it is a replay. The payload is scrubbed of payer and
-- receiver data before it is stored, so anonymous donors' PayPal identity never lands in this table.
CREATE FUNCTION core.fn_record_webhook(p_event_id text, p_event_type text, p_resource_id text, p_payload jsonb)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_clean jsonb; v_rows integer;
BEGIN
    v_clean := p_payload
        #- '{resource,payer}' #- '{resource,payee}' #- '{resource,shipping}'
        #- '{resource,payment_source}' #- '{resource,purchase_units}'
        #- '{resource,payout_item,receiver}' #- '{resource,payout_item,recipient_wallet}'
        #- '{resource,payout_item,sender_batch_id}' #- '{resource,payout_item,note}';
    INSERT INTO core.webhook_events (paypal_event_id, event_type, resource_id, payload)
    VALUES (p_event_id, p_event_type, p_resource_id, v_clean)
    ON CONFLICT (paypal_event_id) DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows = 1;
END $$;

CREATE FUNCTION core.fn_finish_webhook(p_event_id text, p_status core.webhook_status, p_error text DEFAULT NULL)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$ UPDATE core.webhook_events
         SET status = p_status, error = left(p_error, 500), processed_at = now()
       WHERE paypal_event_id = p_event_id $$;

-- ---- donation capture (called by the webhook role, the source of truth for "money arrived") -------------------
CREATE FUNCTION core.fn_mark_donation_captured(p_donation_id uuid, p_capture_id text, p_captured_cents bigint, p_payer_ref_enc bytea)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_amount bigint; v_rows integer;
BEGIN
    SELECT amount_cents INTO v_amount FROM core.donations WHERE id = p_donation_id FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    IF v_amount <> p_captured_cents THEN
        RAISE EXCEPTION 'captured amount does not match the donation' USING ERRCODE = 'check_violation';
    END IF;

    UPDATE core.donations SET status = 'captured', paypal_capture_id = p_capture_id
     WHERE id = p_donation_id AND status = 'initiated';
    GET DIAGNOSTICS v_rows = ROW_COUNT;

    IF v_rows = 1 THEN
        INSERT INTO core.donation_payer_private (donation_id, payer_ref_enc)
        VALUES (p_donation_id, p_payer_ref_enc) ON CONFLICT (donation_id) DO NOTHING;
    END IF;
    RETURN v_rows = 1;          -- FALSE on a replay: safe and idempotent
END $$;

-- Housekeeping: abandoned checkouts are closed so they never clutter reconciliation.
CREATE FUNCTION core.fn_expire_stale_donations(p_older_than interval DEFAULT interval '2 hours')
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_rows integer;
BEGIN
    UPDATE core.donations SET status = 'cancelled'
     WHERE status = 'initiated' AND created_at < now() - p_older_than;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END $$;

-- ---- batching ------------------------------------------------------------------------------------------------------------
-- Atomically claims due queue rows for a recipient that is STILL approved, creates the batch row (with its
-- idempotency key) and marks the rows 'batched'. SKIP LOCKED lets several workers run without overlap.
CREATE FUNCTION core.fn_claim_payout_batch(p_max_items integer, p_sender_batch_id text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_ids uuid[]; v_batch uuid;
BEGIN
    IF p_max_items < 1 OR p_max_items > 15000 THEN
        RAISE EXCEPTION 'p_max_items must be between 1 and 15000' USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT array_agg(s.id) INTO v_ids FROM (
        SELECT q.id FROM core.payout_queue q
         WHERE q.status = 'queued' AND q.next_attempt_at <= now()
           AND EXISTS (SELECT 1 FROM core.recipients_kyc k
                        WHERE k.recipient_id = q.recipient_id AND k.status = 'approved')
         ORDER BY q.queued_at
         LIMIT p_max_items
         FOR UPDATE OF q SKIP LOCKED
    ) s;

    IF v_ids IS NULL THEN RETURN NULL; END IF;

    INSERT INTO core.payout_batches (sender_batch_id, item_count, total_cents)
    SELECT p_sender_batch_id, count(*), sum(amount_cents) FROM core.payout_queue WHERE id = ANY (v_ids)
    RETURNING id INTO v_batch;

    UPDATE core.payout_queue SET status = 'batched', batch_id = v_batch WHERE id = ANY (v_ids);
    RETURN v_batch;
END $$;

-- Everything the worker needs to build the PayPal request. No donor columns exist in this result.
CREATE FUNCTION core.fn_get_batch_items(p_batch_id uuid)
RETURNS TABLE (sender_item_id text, receiver_type core.paypal_receiver_type, receiver_enc bytea,
               amount_cents bigint, currency char(3))
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT q.sender_item_id, r.paypal_receiver_type, r.paypal_receiver_enc, q.amount_cents, q.currency
      FROM core.payout_queue q JOIN core.recipients r ON r.id = q.recipient_id
     WHERE q.batch_id = p_batch_id AND q.status IN ('batched', 'submitted')
     ORDER BY q.queued_at
$$;

CREATE FUNCTION core.fn_get_batch(p_batch_id uuid)
RETURNS TABLE (id uuid, sender_batch_id text, status core.batch_status, attempt_count integer, item_count integer, total_cents bigint)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT b.id, b.sender_batch_id, b.status, b.attempt_count, b.item_count, b.total_cents
        FROM core.payout_batches b WHERE b.id = p_batch_id $$;

-- Crash recovery and retry pickup: returns one batch that is due (never submitted, or waiting to retry) and
-- renews its 2-minute lease so two workers cannot take it at once.
CREATE FUNCTION core.fn_claim_due_batch()
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_id uuid;
BEGIN
    SELECT b.id INTO v_id FROM core.payout_batches b
     WHERE b.status IN ('created', 'retry_wait') AND b.next_attempt_at <= now()
     ORDER BY b.next_attempt_at LIMIT 1
     FOR UPDATE SKIP LOCKED;
    IF v_id IS NULL THEN RETURN NULL; END IF;
    UPDATE core.payout_batches SET status = 'created', next_attempt_at = now() + interval '2 minutes' WHERE id = v_id;
    RETURN v_id;
END $$;

CREATE FUNCTION core.fn_mark_batch_submitted(p_batch_id uuid, p_paypal_batch_id text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    UPDATE core.payout_batches
       SET status = CASE WHEN status IN ('created', 'retry_wait') THEN 'submitted'::core.batch_status ELSE status END,
           paypal_payout_batch_id = COALESCE(paypal_payout_batch_id, p_paypal_batch_id),
           submitted_at = COALESCE(submitted_at, now())
     WHERE id = p_batch_id;
    -- Only rows still 'batched': a fast webhook may already have settled some items.
    UPDATE core.payout_queue SET status = 'submitted' WHERE batch_id = p_batch_id AND status = 'batched';
    INSERT INTO core.ledger_events (event_type, batch_id, amount_cents, source, details)
    SELECT 'batch_submitted', b.id, b.total_cents, 'worker', jsonb_build_object('items', b.item_count)
      FROM core.payout_batches b WHERE b.id = p_batch_id;
END $$;

-- Exponential backoff with jitter: ~30s, 1m, 2m, 4m, 8m ... capped at 1h. Non-retryable errors, or too many
-- attempts, fail the batch and its items, which then show up in the admin grid for a human decision.
CREATE FUNCTION core.fn_batch_submission_failed(p_batch_id uuid, p_error text, p_retryable boolean, p_max_attempts integer DEFAULT 6)
RETURNS core.batch_status
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_attempts integer; v_delay double precision; v_new core.batch_status;
BEGIN
    UPDATE core.payout_batches
       SET attempt_count = attempt_count + 1, last_error = left(p_error, 500)
     WHERE id = p_batch_id AND status IN ('created', 'retry_wait')
    RETURNING attempt_count INTO v_attempts;
    IF NOT FOUND THEN RETURN NULL; END IF;

    IF p_retryable AND v_attempts < p_max_attempts THEN
        v_delay := LEAST(30 * power(2, v_attempts - 1), 3600) * (0.75 + random() * 0.5);
        UPDATE core.payout_batches
           SET status = 'retry_wait', next_attempt_at = now() + make_interval(secs => v_delay)
         WHERE id = p_batch_id;
        v_new := 'retry_wait';
    ELSE
        UPDATE core.payout_batches SET status = 'failed', completed_at = now() WHERE id = p_batch_id;
        UPDATE core.payout_queue SET status = 'failed', failure_reason = 'batch submission failed'
         WHERE batch_id = p_batch_id AND status = 'batched';
        INSERT INTO core.ledger_events (event_type, batch_id, source, details)
        VALUES ('batch_failed', p_batch_id, 'worker', jsonb_build_object('attempts', v_attempts));
        v_new := 'failed';
    END IF;
    RETURN v_new;
END $$;

-- ---- PayPal webhook / reconciler application ---------------------------------------------------------------------------------
-- TRUE when state changed, FALSE when the event was unknown, a duplicate, or stale (out of order).
CREATE FUNCTION core.fn_apply_payout_item_event(p_sender_item_id text, p_new_status core.payout_item_status,
                                                p_paypal_item_id text, p_paypal_txn_status text,
                                                p_failure_reason text, p_event_id text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_id uuid; v_old core.payout_item_status;
BEGIN
    SELECT id, status INTO v_id, v_old FROM core.payout_queue WHERE sender_item_id = p_sender_item_id FOR UPDATE;
    IF NOT FOUND OR v_old = p_new_status THEN RETURN false; END IF;
    IF NOT core.payout_transition_allowed(v_old, p_new_status) THEN RETURN false; END IF;

    UPDATE core.payout_queue
       SET status = p_new_status,
           paypal_payout_item_id = COALESCE(p_paypal_item_id, paypal_payout_item_id),
           paypal_transaction_status = p_paypal_txn_status,
           failure_reason = left(p_failure_reason, 300),
           last_event_id = p_event_id
     WHERE id = v_id;
    RETURN true;
END $$;

CREATE FUNCTION core.fn_apply_batch_event(p_sender_batch_id text, p_paypal_batch_id text,
                                          p_new_status core.batch_status, p_event_id text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_id uuid; v_old core.batch_status;
BEGIN
    SELECT id, status INTO v_id, v_old FROM core.payout_batches
     WHERE (p_sender_batch_id IS NOT NULL AND sender_batch_id = p_sender_batch_id)
        OR (p_paypal_batch_id IS NOT NULL AND paypal_payout_batch_id = p_paypal_batch_id)
     FOR UPDATE;
    IF NOT FOUND OR v_old IN ('success', 'denied', 'failed') OR v_old = p_new_status THEN RETURN false; END IF;
    IF p_new_status NOT IN ('processing', 'success', 'denied') THEN RETURN false; END IF;
    IF p_new_status = 'processing' AND v_old = 'processing' THEN RETURN false; END IF;

    UPDATE core.payout_batches
       SET status = p_new_status,
           paypal_payout_batch_id = COALESCE(paypal_payout_batch_id, p_paypal_batch_id),
           completed_at = CASE WHEN p_new_status IN ('success', 'denied') THEN now() ELSE completed_at END
     WHERE id = v_id;

    IF p_new_status = 'denied' THEN
        UPDATE core.payout_queue SET status = 'failed', failure_reason = 'batch denied by PayPal'
         WHERE batch_id = v_id AND status IN ('batched', 'submitted');
    END IF;

    INSERT INTO core.ledger_events (event_type, batch_id, source, external_event_id)
    VALUES (('batch_' || p_new_status::text)::core.ledger_event_type, v_id, 'webhook', p_event_id);
    RETURN true;
END $$;

-- Reconciler: submitted/processing batches older than the threshold, to be checked against PayPal in case a webhook was lost.
CREATE FUNCTION core.fn_list_stale_batches(p_older_than interval DEFAULT interval '15 minutes')
RETURNS TABLE (id uuid, sender_batch_id text, paypal_payout_batch_id text, status core.batch_status)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT b.id, b.sender_batch_id, b.paypal_payout_batch_id, b.status
        FROM core.payout_batches b
       WHERE b.status IN ('submitted', 'processing') AND b.submitted_at < now() - p_older_than
       ORDER BY b.submitted_at LIMIT 100 $$;

-- Staff: put a failed or blocked payout back in the queue (audited).
CREATE FUNCTION core.fn_requeue_payout(p_payout_id uuid, p_staff_user_id uuid)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role;
BEGIN
    SELECT role INTO v_role FROM core.users WHERE id = p_staff_user_id AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('admin') THEN
        RAISE EXCEPTION 'only an active admin can requeue payouts' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE core.payout_queue SET status = 'queued' WHERE id = p_payout_id AND status IN ('failed', 'blocked');
    IF NOT FOUND THEN RETURN false; END IF;
    PERFORM core.fn_audit(p_staff_user_id, 'payout.requeue', 'payout_queue', p_payout_id::text);
    RETURN true;
END $$;

-- ---- KYC pipeline & review -----------------------------------------------------------------------------------------------------
-- The AI pipeline can only RECOMMEND. This function moves a case to human review and never to 'approved'.
CREATE FUNCTION core.fn_store_kyc_assessment(p_recipient_id uuid, p_extracted_income_cents bigint, p_face_match numeric,
                                             p_fraud_risk numeric, p_flags jsonb, p_recommended_allocation_cents bigint,
                                             p_model_version text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    UPDATE core.recipients_kyc
       SET ai_extracted_monthly_income_cents = p_extracted_income_cents,
           ai_face_match_score = p_face_match,
           ai_fraud_risk_score = p_fraud_risk,
           ai_fraud_flags = COALESCE(p_flags, '[]'::jsonb),
           ai_recommended_allocation_cents = p_recommended_allocation_cents,
           ai_model_version = p_model_version,
           ai_assessed_at = now(),
           status = 'needs_human_review'
     WHERE recipient_id = p_recipient_id AND status = 'processing';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no KYC case in processing state for this recipient' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    PERFORM core.fn_audit(NULL, 'kyc.ai_assessed', 'recipients_kyc', p_recipient_id::text,
                          jsonb_build_object('model', p_model_version));
END $$;

CREATE FUNCTION core.fn_review_kyc(p_recipient_id uuid, p_decision core.kyc_status, p_verified_monthly_income_cents bigint,
                                   p_approved_allocation_cents bigint, p_reviewer_user_id uuid, p_reason text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role;
BEGIN
    SELECT role INTO v_role FROM core.users WHERE id = p_reviewer_user_id AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('reviewer', 'admin') THEN
        RAISE EXCEPTION 'reviewer must be an active reviewer or admin' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_decision NOT IN ('approved', 'rejected', 'suspended') THEN
        RAISE EXCEPTION 'decision must be approved, rejected or suspended' USING ERRCODE = 'invalid_parameter_value';
    END IF;

    UPDATE core.recipients_kyc
       SET status = p_decision,
           verified_monthly_income_cents = CASE WHEN p_decision = 'approved' THEN p_verified_monthly_income_cents
                                                ELSE verified_monthly_income_cents END,
           approved_allocation_cents = CASE WHEN p_decision = 'approved'
                                            THEN COALESCE(p_approved_allocation_cents, ai_recommended_allocation_cents)
                                            ELSE approved_allocation_cents END,
           reviewer_id = p_reviewer_user_id,
           reviewed_at = now(),
           rejection_reason = CASE WHEN p_decision IN ('rejected', 'suspended') THEN left(p_reason, 500) ELSE NULL END
     WHERE recipient_id = p_recipient_id
       AND status IN ('needs_human_review', 'approved', 'suspended');   -- approved/suspended may be revisited
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no reviewable KYC case for this recipient' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    PERFORM core.fn_audit(p_reviewer_user_id, 'kyc.' || p_decision::text, 'recipients_kyc', p_recipient_id::text);
END $$;

CREATE FUNCTION core.fn_moderate_message(p_message_id uuid, p_decision core.moderation_status, p_reason text, p_staff_user_id uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role;
BEGIN
    SELECT role INTO v_role FROM core.users WHERE id = p_staff_user_id AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('reviewer', 'admin') THEN
        RAISE EXCEPTION 'moderator must be an active reviewer or admin' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE core.anonymous_messages
       SET moderation_status = p_decision, moderation_reason = left(p_reason, 300), moderated_at = now()
     WHERE id = p_message_id AND moderation_status = 'pending' AND p_decision IN ('approved', 'rejected');
    IF NOT FOUND THEN RETURN; END IF;
    PERFORM core.fn_audit(p_staff_user_id, 'message.' || p_decision::text, 'anonymous_messages', p_message_id::text);
END $$;

CREATE FUNCTION core.fn_moderate_gratitude(p_note_id uuid, p_decision core.moderation_status, p_staff_user_id uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role;
BEGIN
    SELECT role INTO v_role FROM core.users WHERE id = p_staff_user_id AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('reviewer', 'admin') THEN
        RAISE EXCEPTION 'moderator must be an active reviewer or admin' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE core.gratitude_notes SET moderation_status = p_decision
     WHERE id = p_note_id AND moderation_status = 'pending' AND p_decision IN ('approved', 'rejected');
    IF FOUND THEN
        PERFORM core.fn_audit(p_staff_user_id, 'gratitude.' || p_decision::text, 'gratitude_notes', p_note_id::text);
    END IF;
END $$;

-- =============================================================================
-- 7. ADMIN VIEWS (staff tools). Contain no donor identity and no tracking hashes.
-- =============================================================================
CREATE VIEW core.v_admin_payout_queue AS
SELECT q.id, q.donation_id, q.recipient_id, q.amount_cents, q.currency, q.status, q.batch_id, q.paypal_transaction_status,
       q.failure_reason, q.next_attempt_at, q.queued_at, q.batched_at, q.submitted_at, q.settled_at
  FROM core.payout_queue q;

CREATE VIEW core.v_admin_batches AS
SELECT b.id, b.sender_batch_id, b.paypal_payout_batch_id, b.status, b.item_count, b.total_cents,
       b.attempt_count, b.next_attempt_at, b.last_error, b.created_at, b.submitted_at, b.completed_at
  FROM core.payout_batches b;

CREATE VIEW core.v_admin_ledger AS
SELECT l.id, l.event_type, l.donation_id, l.payout_queue_id, l.batch_id, l.recipient_id, l.amount_cents,
       l.currency, l.source, l.external_event_id, l.details, l.created_at
  FROM core.ledger_events l;

-- Per campaign: does what we recorded as raised equal what the donation rows say, and where is the rest of the money?
CREATE VIEW core.v_admin_reconciliation AS
SELECT c.id AS campaign_id, c.recipient_id, c.raised_cents, c.paid_out_cents,
       COALESCE(d.captured_gross, 0)                     AS donations_captured_cents,
       COALESCE(p.queued_cents, 0)                       AS payout_queued_cents,
       COALESCE(p.in_flight_cents, 0)                    AS payout_in_flight_cents,
       COALESCE(p.unclaimed_cents, 0)                    AS payout_unclaimed_cents,
       COALESCE(p.problem_cents, 0)                      AS payout_problem_cents,
       COALESCE(p.delivered_cents, 0)                    AS payout_delivered_cents,
       (c.raised_cents <> COALESCE(d.captured_gross, 0)) AS raised_mismatch,
       (c.paid_out_cents <> COALESCE(p.delivered_cents, 0)) AS paid_out_mismatch
  FROM core.campaigns c
  LEFT JOIN (SELECT campaign_id, sum(amount_cents) AS captured_gross
               FROM core.donations WHERE status IN ('captured', 'paid_out') GROUP BY campaign_id) d
         ON d.campaign_id = c.id
  LEFT JOIN (SELECT dn.campaign_id,
                    sum(q.amount_cents) FILTER (WHERE q.status = 'queued')                          AS queued_cents,
                    sum(q.amount_cents) FILTER (WHERE q.status IN ('batched', 'submitted', 'held')) AS in_flight_cents,
                    sum(q.amount_cents) FILTER (WHERE q.status = 'unclaimed')                       AS unclaimed_cents,
                    sum(q.amount_cents) FILTER (WHERE q.status IN ('failed', 'blocked', 'returned')) AS problem_cents,
                    sum(q.amount_cents) FILTER (WHERE q.status = 'succeeded')                       AS delivered_cents
               FROM core.payout_queue q JOIN core.donations dn ON dn.id = q.donation_id
              GROUP BY dn.campaign_id) p
         ON p.campaign_id = c.id;

CREATE VIEW core.v_admin_kyc_queue AS
SELECT k.recipient_id, k.status, k.ai_extracted_monthly_income_cents, k.ai_face_match_score, k.ai_fraud_risk_score,
       k.ai_fraud_flags, k.ai_recommended_allocation_cents, k.ai_model_version, k.ai_assessed_at, k.created_at, k.updated_at
  FROM core.recipients_kyc k
 WHERE k.status IN ('processing', 'needs_human_review');

CREATE VIEW core.v_admin_message_queue AS
SELECT m.id, m.donation_id, m.sender, m.body_enc, m.created_at     -- body is ciphertext; the admin service decrypts
  FROM core.anonymous_messages m WHERE m.moderation_status = 'pending';

CREATE VIEW core.v_admin_gratitude_queue AS
SELECT g.id, g.recipient_id, g.is_community, g.body, g.created_at
  FROM core.gratitude_notes g WHERE g.moderation_status = 'pending';

-- =============================================================================
-- 8. PUBLIC / API SURFACE (schema api)
--    Views run with the owner's rights, so the API role reads masked columns only.
-- =============================================================================

CREATE VIEW api.public_campaigns AS
SELECT c.id, c.slug, c.title, c.story, c.cover_object_key, c.goal_cents, c.raised_cents, c.status,
       r.slug AS recipient_slug, r.public_name AS recipient_name, r.business_type,
       r.region_country, r.region_admin1,
       (SELECT count(*) FROM core.donations d WHERE d.campaign_id = c.id AND d.status IN ('captured', 'paid_out')) AS donor_count,
       c.created_at
  FROM core.campaigns c
  JOIN core.recipients r     ON r.id = c.recipient_id
  JOIN core.recipients_kyc k ON k.recipient_id = r.id
 WHERE r.profile_public AND k.status = 'approved' AND c.status IN ('active', 'funded');

CREATE VIEW api.public_campaign_updates AS
SELECT u.id, c.slug AS campaign_slug, u.body, u.media_object_keys, u.created_at
  FROM core.campaign_updates u
  JOIN api.public_campaigns c ON c.id = u.campaign_id
 WHERE u.visibility = 'public';

CREATE VIEW api.public_campaign_comments AS
SELECT cm.id, c.slug AS campaign_slug, COALESCE(u.display_name, 'SadQah friend') AS author_name,
       cm.body, cm.media_object_key, cm.created_at
  FROM core.campaign_comments cm
  JOIN api.public_campaigns c ON c.id = cm.campaign_id
  JOIN core.users u           ON u.id = cm.author_user_id
 WHERE cm.moderation_status = 'approved';

-- Recent gifts. Anonymous donors: no name, no user id, no token, and the time is truncated to the day.
CREATE VIEW api.public_donation_feed AS
SELECT d.id AS feed_id_hint,
       c.slug AS campaign_slug,
       d.amount_cents,
       d.is_anonymous,
       CASE WHEN d.is_anonymous THEN 'Anonymous' ELSE COALESCE(u.display_name, 'SadQah friend') END AS donor_label,
       CASE WHEN d.is_anonymous THEN date_trunc('day', d.captured_at) ELSE d.captured_at END AS given_at
  FROM core.donations d
  JOIN core.campaigns c ON c.id = d.campaign_id
  LEFT JOIN core.users u ON u.id = d.donor_user_id AND NOT d.is_anonymous
 WHERE d.status IN ('captured', 'paid_out');
COMMENT ON VIEW api.public_donation_feed IS
    'feed_id_hint is a donation UUID that is only meaningful to the donor. Clients must not use it as a link key for anonymous gifts; the API replaces it with a row counter before responding.';

CREATE VIEW api.public_leaderboard AS
SELECT rank() OVER (ORDER BY l.points DESC) AS rank,
       COALESCE(u.display_name, 'SadQah friend') AS donor_label,
       u.country_code, l.points, l.donation_count
  FROM core.leaderboard l
  JOIN core.users u ON u.id = l.user_id
 WHERE l.show_publicly AND u.is_active AND l.points > 0;

CREATE VIEW api.public_gratitude_wall AS
SELECT g.id, r.public_name AS recipient_name, c.slug AS campaign_slug,
       CASE WHEN g.is_community THEN 'the SadQah community' ELSE COALESCE(u.display_name, 'a SadQah friend') END AS thanks_to,
       g.body, g.created_at
  FROM core.gratitude_notes g
  JOIN core.recipients r ON r.id = g.recipient_id
  JOIN core.donations d  ON d.id = g.donation_id
  JOIN core.campaigns c  ON c.id = d.campaign_id
  LEFT JOIN core.users u ON u.id = g.to_user_id
 WHERE g.moderation_status = 'approved';

CREATE VIEW api.public_impact_stats AS
SELECT (SELECT count(*) FROM core.recipients r JOIN core.recipients_kyc k ON k.recipient_id = r.id
         WHERE r.profile_public AND k.status = 'approved')                                    AS recipients_supported,
       (SELECT count(DISTINCT r.region_country) FROM core.recipients r
         WHERE r.profile_public)                                                               AS countries_reached,
       (SELECT count(*) FROM core.donations WHERE status IN ('captured', 'paid_out'))          AS gifts_given,
       (SELECT COALESCE(sum(amount_cents), 0) FROM core.donations
         WHERE status IN ('captured', 'paid_out'))                                             AS total_given_cents;

-- Logged-in donors see their own PUBLIC gifts. Anonymous gifts have no donor id, so they cannot appear here: by design.
CREATE VIEW api.my_donations AS
SELECT d.id, c.slug AS campaign_slug, c.title AS campaign_title, d.amount_cents, d.status, d.created_at, d.paid_out_at,
       (d.status = 'paid_out') AS thread_open
  FROM core.donations d
  JOIN core.campaigns c ON c.id = d.campaign_id
 WHERE d.donor_user_id = core.current_user_id();

CREATE VIEW api.my_pledge AS
SELECT p.id, p.kind, p.percent, p.amount_cents, p.frequency, p.default_anonymous, p.created_at
  FROM core.donor_pledges p
 WHERE p.user_id = core.current_user_id() AND p.active;

CREATE VIEW api.my_gratitude AS
SELECT g.id, g.donation_id, r.public_name AS recipient_name, g.body, g.created_at
  FROM core.gratitude_notes g
  JOIN core.recipients r ON r.id = g.recipient_id
 WHERE g.to_user_id = core.current_user_id() AND g.moderation_status = 'approved';

CREATE VIEW api.my_recipient_profile AS
SELECT r.id, r.slug, r.public_name, r.story, r.business_type, r.region_country, r.region_admin1,
       r.profile_public, k.status AS kyc_status, k.rejection_reason, k.approved_allocation_cents
  FROM core.recipients r
  JOIN core.recipients_kyc k ON k.recipient_id = r.id
 WHERE r.user_id = core.current_user_id();

-- ---- auth ---------------------------------------------------------------------------------------------------------------------------
CREATE FUNCTION api.fn_register_user(p_email_enc bytea, p_email_blind_idx bytea, p_phone_enc bytea, p_phone_blind_idx bytea,
                                     p_password_hash text, p_role core.user_role, p_display_name text, p_country_code char)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_id uuid;
BEGIN
    IF p_role NOT IN ('donor', 'recipient') THEN
        RAISE EXCEPTION 'self-registration is limited to donor and recipient roles' USING ERRCODE = 'insufficient_privilege';
    END IF;
    INSERT INTO core.users (role, email_enc, email_blind_idx, phone_enc, phone_blind_idx, password_hash, display_name, country_code)
    VALUES (p_role, p_email_enc, p_email_blind_idx, p_phone_enc, p_phone_blind_idx, p_password_hash,
            p_display_name, upper(p_country_code))
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

CREATE FUNCTION api.fn_auth_get_user(p_email_blind_idx bytea)
RETURNS TABLE (id uuid, role core.user_role, password_hash text, is_active boolean, locked_until timestamptz,
               failed_login_count integer, email_verified_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT u.id, u.role, u.password_hash, u.is_active, u.locked_until, u.failed_login_count, u.email_verified_at
        FROM core.users u WHERE u.email_blind_idx = p_email_blind_idx $$;

-- Records a login attempt. Five failures lock the account for 15 minutes.
CREATE FUNCTION api.fn_auth_record_login(p_user_id uuid, p_success boolean)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF p_success THEN
        UPDATE core.users SET failed_login_count = 0, locked_until = NULL, last_login_at = now() WHERE id = p_user_id;
    ELSE
        UPDATE core.users
           SET failed_login_count = failed_login_count + 1,
               locked_until = CASE WHEN failed_login_count + 1 >= 5 THEN now() + interval '15 minutes' ELSE locked_until END
         WHERE id = p_user_id;
    END IF;
END $$;

CREATE FUNCTION api.fn_get_me()
RETURNS TABLE (id uuid, role core.user_role, email_enc bytea, phone_enc bytea, display_name text, country_code char)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT u.id, u.role, u.email_enc, u.phone_enc, u.display_name, u.country_code
        FROM core.users u WHERE u.id = core.current_user_id() AND u.is_active $$;

CREATE FUNCTION api.fn_set_display_name(p_display_name text)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$ UPDATE core.users SET display_name = p_display_name WHERE id = core.current_user_id() $$;

CREATE FUNCTION api.fn_set_leaderboard_visibility(p_show boolean)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$ UPDATE core.leaderboard SET show_publicly = p_show WHERE user_id = core.current_user_id() $$;

-- ---- donations ----------------------------------------------------------------------------------------------------------------------
-- Creates the donation row (UUID bound to the recipient) BEFORE PayPal is contacted.
-- Public: p_donor_user_id must equal the session user. Anonymous: it must be NULL.
CREATE FUNCTION api.fn_create_donation(p_campaign_slug text, p_amount_cents bigint, p_is_anonymous boolean,
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

CREATE FUNCTION api.fn_attach_paypal_order(p_donation_id uuid, p_order_id text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    UPDATE core.donations SET paypal_order_id = p_order_id
     WHERE id = p_donation_id AND status = 'initiated' AND paypal_order_id IS NULL;
    RETURN FOUND;
END $$;

-- ---- anonymous tracking (token holder). The same generic error for "no such token" avoids probing. ------------------------------------
CREATE FUNCTION api.fn_track_donation(p_token_hash bytea)
RETURNS TABLE (donation_id uuid, amount_cents bigint, donation_status core.donation_status, delivery_state text,
               thread_open boolean, given_at date, campaign_slug text, campaign_title text, recipient_slug text,
               recipient_name text, region_country char, region_admin1 text, gratitude_body text, gratitude_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT d.id, d.amount_cents, d.status,
           CASE q.status
                WHEN 'succeeded' THEN 'delivered'
                WHEN 'unclaimed' THEN 'awaiting_recipient_claim'
                WHEN 'queued'    THEN 'queued_for_next_batch'
                WHEN 'batched'   THEN 'being_prepared'
                WHEN 'submitted' THEN 'on_its_way'
                WHEN 'held'      THEN 'on_its_way'
                ELSE 'needs_attention' END,
           (d.status = 'paid_out'),
           d.created_at::date, c.slug, c.title, r.slug, r.public_name, r.region_country, r.region_admin1,
           g.body, g.created_at
      FROM core.donations d
      JOIN core.campaigns c  ON c.id = d.campaign_id
      JOIN core.recipients r ON r.id = d.recipient_id
      LEFT JOIN core.payout_queue q ON q.donation_id = d.id
      LEFT JOIN core.gratitude_notes g ON g.donation_id = d.id AND g.moderation_status = 'approved'
     WHERE d.tracking_token_hash = p_token_hash AND d.status IN ('captured', 'paid_out')
$$;

-- Profile updates for the campaign the token helped, including donors-only updates.
CREATE FUNCTION api.fn_track_updates(p_token_hash bytea)
RETURNS TABLE (id uuid, body text, media_object_keys text[], visibility core.update_visibility, created_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT u.id, u.body, u.media_object_keys, u.visibility, u.created_at
      FROM core.donations d JOIN core.campaign_updates u ON u.campaign_id = d.campaign_id
     WHERE d.tracking_token_hash = p_token_hash AND d.status IN ('captured', 'paid_out')
     ORDER BY u.created_at DESC
$$;

CREATE FUNCTION api.fn_track_thread(p_token_hash bytea)
RETURNS TABLE (id uuid, sender core.message_sender, body_enc bytea, moderation_status core.moderation_status, created_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT m.id, m.sender, m.body_enc, m.moderation_status, m.created_at
      FROM core.donations d JOIN core.anonymous_messages m ON m.donation_id = d.id
     WHERE d.tracking_token_hash = p_token_hash
       AND (m.sender = 'donor' OR m.moderation_status = 'approved')
     ORDER BY m.created_at
$$;

CREATE FUNCTION api.fn_donor_post_message(p_token_hash bytea, p_body_enc bytea)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_donation uuid; v_recent integer; v_id uuid;
BEGIN
    SELECT id INTO v_donation FROM core.donations WHERE tracking_token_hash = p_token_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'invalid token' USING ERRCODE = 'invalid_authorization_specification';
    END IF;
    SELECT count(*) INTO v_recent FROM core.anonymous_messages
     WHERE donation_id = v_donation AND sender = 'donor' AND created_at > now() - interval '24 hours';
    IF v_recent >= 10 THEN
        RAISE EXCEPTION 'message limit reached for today' USING ERRCODE = 'program_limit_exceeded';
    END IF;
    INSERT INTO core.anonymous_messages (donation_id, sender, body_enc)
    VALUES (v_donation, 'donor', p_body_enc) RETURNING id INTO v_id;
    RETURN v_id;
END $$;

CREATE FUNCTION api.fn_donor_mark_read(p_token_hash bytea)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
    UPDATE core.anonymous_messages m SET read_by_donor_at = now()
      FROM core.donations d
     WHERE d.id = m.donation_id AND d.tracking_token_hash = p_token_hash
       AND m.sender = 'recipient' AND m.moderation_status = 'approved' AND m.read_by_donor_at IS NULL
$$;

-- ---- recipient-side messaging (never reveals donor identity for anonymous gifts) ---------------------------------------------------------
CREATE FUNCTION api.fn_recipient_threads()
RETURNS TABLE (thread_id uuid, campaign_slug text, is_anonymous boolean, donor_label text, amount_cents bigint,
               paid_out_at timestamptz, last_message_at timestamptz, unread_count bigint)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT d.id, c.slug, d.is_anonymous,
           CASE WHEN d.is_anonymous THEN 'A SadQah donor' ELSE COALESCE(u.display_name, 'A SadQah donor') END,
           d.amount_cents,
           CASE WHEN d.is_anonymous THEN date_trunc('day', d.paid_out_at) ELSE d.paid_out_at END,
           max(m.created_at) FILTER (WHERE m.sender = 'recipient' OR m.moderation_status = 'approved'),
           count(m.id) FILTER (WHERE m.sender = 'donor' AND m.moderation_status = 'approved' AND m.read_by_recipient_at IS NULL)
      FROM core.donations d
      JOIN core.recipients r ON r.id = d.recipient_id
      JOIN core.campaigns c  ON c.id = d.campaign_id
      LEFT JOIN core.users u ON u.id = d.donor_user_id
      LEFT JOIN core.anonymous_messages m ON m.donation_id = d.id
     WHERE r.user_id = core.current_user_id() AND d.status = 'paid_out'
     GROUP BY d.id, c.id, u.id
     ORDER BY d.paid_out_at DESC
$$;

CREATE FUNCTION api.fn_recipient_thread_messages(p_donation_id uuid)
RETURNS TABLE (id uuid, sender core.message_sender, body_enc bytea, moderation_status core.moderation_status, created_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT m.id, m.sender, m.body_enc, m.moderation_status, m.created_at
      FROM core.anonymous_messages m
      JOIN core.donations d  ON d.id = m.donation_id
      JOIN core.recipients r ON r.id = d.recipient_id
     WHERE m.donation_id = p_donation_id AND r.user_id = core.current_user_id()
       AND (m.sender = 'recipient' OR m.moderation_status = 'approved')
     ORDER BY m.created_at
$$;

CREATE FUNCTION api.fn_recipient_post_message(p_donation_id uuid, p_body_enc bytea)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_recent integer; v_id uuid;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM core.donations d JOIN core.recipients r ON r.id = d.recipient_id
                    WHERE d.id = p_donation_id AND r.user_id = core.current_user_id()) THEN
        RAISE EXCEPTION 'thread not found' USING ERRCODE = 'invalid_authorization_specification';
    END IF;
    SELECT count(*) INTO v_recent FROM core.anonymous_messages
     WHERE donation_id = p_donation_id AND sender = 'recipient' AND created_at > now() - interval '24 hours';
    IF v_recent >= 10 THEN
        RAISE EXCEPTION 'message limit reached for today' USING ERRCODE = 'program_limit_exceeded';
    END IF;
    INSERT INTO core.anonymous_messages (donation_id, sender, body_enc)
    VALUES (p_donation_id, 'recipient', p_body_enc) RETURNING id INTO v_id;
    RETURN v_id;
END $$;

CREATE FUNCTION api.fn_recipient_mark_read(p_donation_id uuid)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
    UPDATE core.anonymous_messages m SET read_by_recipient_at = now()
      FROM core.donations d JOIN core.recipients r ON r.id = d.recipient_id
     WHERE d.id = m.donation_id AND m.donation_id = p_donation_id AND r.user_id = core.current_user_id()
       AND m.sender = 'donor' AND m.moderation_status = 'approved' AND m.read_by_recipient_at IS NULL
$$;

-- ---- gratitude: the recipient picks the donation; the database picks the audience --------------------------------------------------------
CREATE FUNCTION api.fn_post_gratitude(p_donation_id uuid, p_body text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE d core.donations%ROWTYPE; v_recipient uuid; v_id uuid;
BEGIN
    SELECT r.id INTO v_recipient FROM core.recipients r WHERE r.user_id = core.current_user_id();
    SELECT * INTO d FROM core.donations WHERE id = p_donation_id AND recipient_id = v_recipient;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'donation not found' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    INSERT INTO core.gratitude_notes (donation_id, recipient_id, to_user_id, is_community, body)
    VALUES (d.id, v_recipient, d.donor_user_id, d.is_anonymous, p_body)
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- ---- pledges (1% to 5% of yearly income, or any fixed amount; income is computed client-side and never stored) --------------------------
CREATE FUNCTION api.fn_set_pledge(p_kind core.pledge_kind, p_percent numeric, p_amount_cents bigint,
                                  p_frequency core.pledge_frequency, p_default_anonymous boolean)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_user uuid := core.current_user_id(); v_id uuid;
BEGIN
    IF v_user IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE core.donor_pledges SET active = false WHERE user_id = v_user AND active;
    INSERT INTO core.donor_pledges (user_id, kind, percent, amount_cents, frequency, default_anonymous)
    VALUES (v_user, p_kind, p_percent, p_amount_cents, p_frequency, p_default_anonymous)
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

CREATE FUNCTION api.fn_clear_pledge()
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$ UPDATE core.donor_pledges SET active = false WHERE user_id = core.current_user_id() AND active $$;

-- ---- community comments -------------------------------------------------------------------------------------------------------------------
CREATE FUNCTION api.fn_post_comment(p_campaign_slug text, p_body text, p_media_object_key text, p_moderation core.moderation_status)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_user uuid := core.current_user_id(); v_campaign uuid; v_id uuid;
BEGIN
    IF v_user IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_moderation NOT IN ('pending', 'approved') THEN
        RAISE EXCEPTION 'invalid initial moderation state' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT id INTO v_campaign FROM api.public_campaigns WHERE slug = p_campaign_slug;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown campaign' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    INSERT INTO core.campaign_comments (campaign_id, author_user_id, body, media_object_key, moderation_status)
    VALUES (v_campaign, v_user, p_body, p_media_object_key, p_moderation) RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- ---- recipient onboarding ---------------------------------------------------------------------------------------------------------------------
CREATE FUNCTION api.fn_create_recipient_profile(p_slug text, p_public_name text, p_story text, p_business_type text,
                                                p_region_country char, p_region_admin1 text,
                                                p_receiver_type core.paypal_receiver_type, p_receiver_enc bytea,
                                                p_receiver_blind_idx bytea)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_user uuid := core.current_user_id(); v_id uuid;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM core.users WHERE id = v_user AND role = 'recipient' AND is_active) THEN
        RAISE EXCEPTION 'recipient account required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    INSERT INTO core.recipients (user_id, slug, public_name, story, business_type, region_country, region_admin1,
                                 paypal_receiver_type, paypal_receiver_enc, paypal_receiver_blind_idx)
    VALUES (v_user, p_slug, p_public_name, COALESCE(p_story, ''), p_business_type, upper(p_region_country), p_region_admin1,
            p_receiver_type, p_receiver_enc, p_receiver_blind_idx)
    RETURNING id INTO v_id;
    INSERT INTO core.recipients_kyc (recipient_id) VALUES (v_id);
    RETURN v_id;
END $$;

CREATE FUNCTION api.fn_set_profile_public(p_public boolean)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    UPDATE core.recipients
       SET profile_public = p_public,
           consent_public_profile_at = CASE WHEN p_public THEN COALESCE(consent_public_profile_at, now())
                                            ELSE consent_public_profile_at END
     WHERE user_id = core.current_user_id();
END $$;

CREATE FUNCTION api.fn_create_campaign(p_slug text, p_title text, p_story text, p_goal_cents bigint)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_recipient uuid; v_id uuid;
BEGIN
    SELECT id INTO v_recipient FROM core.recipients WHERE user_id = core.current_user_id();
    IF v_recipient IS NULL THEN
        RAISE EXCEPTION 'recipient profile required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    INSERT INTO core.campaigns (recipient_id, slug, title, story, goal_cents, status)
    VALUES (v_recipient, p_slug, p_title, COALESCE(p_story, ''), p_goal_cents, 'active')
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

CREATE FUNCTION api.fn_post_campaign_update(p_body text, p_media_object_keys text[], p_visibility core.update_visibility)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_campaign uuid; v_id uuid;
BEGIN
    SELECT c.id INTO v_campaign
      FROM core.campaigns c JOIN core.recipients r ON r.id = c.recipient_id
     WHERE r.user_id = core.current_user_id() AND c.status IN ('active', 'funded')
     ORDER BY c.created_at DESC LIMIT 1;
    IF v_campaign IS NULL THEN
        RAISE EXCEPTION 'no live campaign' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    INSERT INTO core.campaign_updates (campaign_id, body, media_object_keys, visibility)
    VALUES (v_campaign, p_body, COALESCE(p_media_object_keys, '{}'), p_visibility) RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- ---- KYC (recipient side) -------------------------------------------------------------------------------------------------------------------------
CREATE FUNCTION api.fn_kyc_save_identity(p_full_name_enc bytea, p_dob_enc bytea, p_nic_enc bytea, p_nic_blind_idx bytea,
                                         p_address_enc bytea, p_doc_country char, p_consent_biometric boolean,
                                         p_consent_data boolean)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_recipient uuid;
BEGIN
    SELECT id INTO v_recipient FROM core.recipients WHERE user_id = core.current_user_id();
    IF v_recipient IS NULL THEN
        RAISE EXCEPTION 'recipient profile required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT (p_consent_biometric AND p_consent_data) THEN
        RAISE EXCEPTION 'explicit consent for biometric and personal data processing is required' USING ERRCODE = 'check_violation';
    END IF;
    UPDATE core.recipients_kyc
       SET full_name_enc = p_full_name_enc, dob_enc = p_dob_enc, nic_number_enc = p_nic_enc, nic_blind_idx = p_nic_blind_idx,
           address_enc = p_address_enc, doc_country = upper(p_doc_country),
           consent_biometric_at = COALESCE(consent_biometric_at, now()),
           consent_data_at = COALESCE(consent_data_at, now()),
           data_retention_until = COALESCE(data_retention_until, now() + interval '2 years'),
           status = CASE WHEN status = 'not_started' THEN 'documents_pending'::core.kyc_status ELSE status END
     WHERE recipient_id = v_recipient AND status IN ('not_started', 'documents_pending', 'rejected');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'KYC cannot be edited in its current state' USING ERRCODE = 'check_violation';
    END IF;
END $$;

CREATE FUNCTION api.fn_kyc_register_document(p_doc_type core.kyc_doc_type, p_object_key text, p_sha256 bytea,
                                             p_mime_type text, p_size_bytes bigint, p_wrapped_dek bytea)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_recipient uuid; v_status core.kyc_status; v_id uuid;
BEGIN
    SELECT r.id, k.status INTO v_recipient, v_status
      FROM core.recipients r JOIN core.recipients_kyc k ON k.recipient_id = r.id
     WHERE r.user_id = core.current_user_id();
    IF v_recipient IS NULL OR v_status NOT IN ('not_started', 'documents_pending', 'rejected') THEN
        RAISE EXCEPTION 'documents cannot be added in the current KYC state' USING ERRCODE = 'check_violation';
    END IF;
    -- A new selfie or document of a single-instance type replaces the previous one.
    IF p_doc_type IN ('selfie', 'national_id', 'passport') THEN
        UPDATE core.kyc_documents SET deleted_at = now()
         WHERE recipient_id = v_recipient AND doc_type = p_doc_type AND deleted_at IS NULL;
    END IF;
    INSERT INTO core.kyc_documents (recipient_id, doc_type, object_key, sha256, mime_type, size_bytes, wrapped_dek)
    VALUES (v_recipient, p_doc_type, p_object_key, p_sha256, p_mime_type, p_size_bytes, p_wrapped_dek)
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- Submit for AI assessment: needs identity data, consent, an ID document, proof of address, a selfie, and proof of income.
CREATE FUNCTION api.fn_kyc_submit()
RETURNS text[]
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_recipient uuid; k core.recipients_kyc%ROWTYPE; v_missing text[] := '{}';
BEGIN
    SELECT id INTO v_recipient FROM core.recipients WHERE user_id = core.current_user_id();
    SELECT * INTO k FROM core.recipients_kyc WHERE recipient_id = v_recipient;
    IF NOT FOUND OR k.status NOT IN ('documents_pending', 'rejected') THEN
        RAISE EXCEPTION 'KYC cannot be submitted in its current state' USING ERRCODE = 'check_violation';
    END IF;

    IF k.nic_blind_idx IS NULL OR k.consent_biometric_at IS NULL OR k.consent_data_at IS NULL THEN
        v_missing := array_append(v_missing, 'identity_details_and_consent');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.kyc_documents WHERE recipient_id = v_recipient AND deleted_at IS NULL
                      AND doc_type IN ('national_id', 'passport') AND scan_status <> 'infected') THEN
        v_missing := array_append(v_missing, 'national_id_or_passport');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.kyc_documents WHERE recipient_id = v_recipient AND deleted_at IS NULL
                      AND doc_type = 'utility_bill' AND scan_status <> 'infected') THEN
        v_missing := array_append(v_missing, 'utility_bill');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.kyc_documents WHERE recipient_id = v_recipient AND deleted_at IS NULL
                      AND doc_type = 'selfie' AND scan_status <> 'infected') THEN
        v_missing := array_append(v_missing, 'selfie');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core.kyc_documents WHERE recipient_id = v_recipient AND deleted_at IS NULL
                      AND doc_type IN ('bank_statement', 'proof_of_income') AND scan_status <> 'infected') THEN
        v_missing := array_append(v_missing, 'bank_statement_or_proof_of_income');
    END IF;

    IF cardinality(v_missing) = 0 THEN
        UPDATE core.recipients_kyc SET status = 'processing', rejection_reason = NULL WHERE recipient_id = v_recipient;
    END IF;
    RETURN v_missing;
END $$;

-- =============================================================================
-- 8b. RECIPIENT DASHBOARD, PROFILE EDITING, KYC CONTEXT, WORKER GATE
--     Added while building the backend: every read the portal needs, still without table rights.
-- =============================================================================

CREATE VIEW api.my_campaign AS
SELECT c.slug, c.title, c.story, c.goal_cents, c.raised_cents, c.paid_out_cents, c.status, c.created_at
  FROM core.campaigns c
  JOIN core.recipients r ON r.id = c.recipient_id
 WHERE r.user_id = core.current_user_id();

-- KYC progress for the signed-in recipient. Document metadata only: no keys, no hashes.
CREATE FUNCTION api.fn_kyc_my_status()
RETURNS TABLE (status core.kyc_status, rejection_reason text, approved_allocation_cents bigint,
               identity_saved boolean, documents jsonb)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT k.status, k.rejection_reason, k.approved_allocation_cents,
           (k.nic_blind_idx IS NOT NULL AND k.consent_data_at IS NOT NULL AND k.consent_biometric_at IS NOT NULL),
           COALESCE((SELECT jsonb_agg(jsonb_build_object('doc_type', d.doc_type,
                                                         'uploaded_at', d.uploaded_at,
                                                         'scan_status', d.scan_status) ORDER BY d.uploaded_at)
                       FROM core.kyc_documents d
                      WHERE d.recipient_id = r.id AND d.deleted_at IS NULL), '[]'::jsonb)
      FROM core.recipients r JOIN core.recipients_kyc k ON k.recipient_id = r.id
     WHERE r.user_id = core.current_user_id()
$$;

-- Where is the recipient's money? Derived from the same rows the reconciliation view uses.
CREATE FUNCTION api.fn_recipient_balance()
RETURNS TABLE (raised_cents bigint, queued_cents bigint, in_flight_cents bigint, unclaimed_cents bigint,
               delivered_cents bigint, problem_cents bigint)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT COALESCE((SELECT sum(d.amount_cents) FROM core.donations d
                      WHERE d.recipient_id = r.id AND d.status IN ('captured', 'paid_out')), 0)::bigint,
           COALESCE(sum(q.amount_cents) FILTER (WHERE q.status = 'queued'), 0)::bigint,
           COALESCE(sum(q.amount_cents) FILTER (WHERE q.status IN ('batched', 'submitted', 'held')), 0)::bigint,
           COALESCE(sum(q.amount_cents) FILTER (WHERE q.status = 'unclaimed'), 0)::bigint,
           COALESCE(sum(q.amount_cents) FILTER (WHERE q.status = 'succeeded'), 0)::bigint,
           COALESCE(sum(q.amount_cents) FILTER (WHERE q.status IN ('failed', 'blocked', 'returned')), 0)::bigint
      FROM core.recipients r
      LEFT JOIN core.payout_queue q ON q.recipient_id = r.id
     WHERE r.user_id = core.current_user_id()
     GROUP BY r.id
$$;

-- The recipient's own gifts. Anonymous donors are labelled generically and their timestamps are truncated to the day.
CREATE FUNCTION api.fn_recipient_donations()
RETURNS TABLE (donation_id uuid, campaign_slug text, is_anonymous boolean, donor_label text, amount_cents bigint,
               donation_status core.donation_status, delivery_state text, captured_at timestamptz,
               paid_out_at timestamptz, has_gratitude boolean)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT d.id, c.slug, d.is_anonymous,
           CASE WHEN d.is_anonymous THEN 'An anonymous donor' ELSE COALESCE(u.display_name, 'A SadQah friend') END,
           d.amount_cents, d.status,
           CASE q.status
                WHEN 'succeeded' THEN 'delivered'
                WHEN 'unclaimed' THEN 'awaiting_recipient_claim'
                WHEN 'queued'    THEN 'queued_for_next_batch'
                WHEN 'batched'   THEN 'being_prepared'
                WHEN 'submitted' THEN 'on_its_way'
                WHEN 'held'      THEN 'on_its_way'
                ELSE 'needs_attention' END,
           CASE WHEN d.is_anonymous THEN date_trunc('day', d.captured_at) ELSE d.captured_at END,
           CASE WHEN d.is_anonymous THEN date_trunc('day', d.paid_out_at) ELSE d.paid_out_at END,
           EXISTS (SELECT 1 FROM core.gratitude_notes g WHERE g.donation_id = d.id)
      FROM core.donations d
      JOIN core.recipients r  ON r.id = d.recipient_id
      JOIN core.campaigns c   ON c.id = d.campaign_id
      LEFT JOIN core.users u  ON u.id = d.donor_user_id AND NOT d.is_anonymous
      LEFT JOIN core.payout_queue q ON q.donation_id = d.id
     WHERE r.user_id = core.current_user_id() AND d.status IN ('captured', 'paid_out')
     ORDER BY d.captured_at DESC
$$;

CREATE FUNCTION api.fn_update_recipient_profile(p_public_name text, p_story text, p_business_type text, p_region_admin1 text)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
    UPDATE core.recipients
       SET public_name   = COALESCE(p_public_name, public_name),
           story         = COALESCE(p_story, story),
           business_type = COALESCE(p_business_type, business_type),
           region_admin1 = COALESCE(p_region_admin1, region_admin1)
     WHERE user_id = core.current_user_id()
$$;

-- Redirection fraud guard: the payout destination can only change BEFORE verification is approved.
CREATE FUNCTION api.fn_set_payout_receiver(p_type core.paypal_receiver_type, p_receiver_enc bytea, p_receiver_blind_idx bytea)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_recipient uuid; v_status core.kyc_status;
BEGIN
    SELECT r.id, k.status INTO v_recipient, v_status
      FROM core.recipients r JOIN core.recipients_kyc k ON k.recipient_id = r.id
     WHERE r.user_id = core.current_user_id();
    IF v_recipient IS NULL THEN
        RAISE EXCEPTION 'recipient profile required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_status NOT IN ('not_started', 'documents_pending', 'rejected') THEN
        RAISE EXCEPTION 'the payout destination is locked once verification is under review or approved; contact support to change it'
            USING ERRCODE = 'check_violation';
    END IF;
    UPDATE core.recipients
       SET paypal_receiver_type = p_type, paypal_receiver_enc = p_receiver_enc, paypal_receiver_blind_idx = p_receiver_blind_idx
     WHERE id = v_recipient;
END $$;

-- KYC pipeline: the business context the allocation model may use (never contact details).
CREATE FUNCTION core.fn_kyc_case_context(p_recipient_id uuid)
RETURNS TABLE (public_name text, business_type text, story text, region_country char, region_admin1 text)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT r.public_name, r.business_type, r.story, r.region_country, r.region_admin1
        FROM core.recipients r WHERE r.id = p_recipient_id $$;

-- Payout worker gate: lets the worker decide "enough queued, or waited long enough" without any table rights.
CREATE FUNCTION core.fn_payout_queue_stats()
RETURNS TABLE (ready_count bigint, ready_cents bigint, oldest_queued_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT count(*), COALESCE(sum(q.amount_cents), 0)::bigint, min(q.queued_at)
      FROM core.payout_queue q
     WHERE q.status = 'queued' AND q.next_attempt_at <= now()
       AND EXISTS (SELECT 1 FROM core.recipients_kyc k WHERE k.recipient_id = q.recipient_id AND k.status = 'approved')
$$;

-- Staff: every time a reviewer opens a KYC document, that fact is written to the audit log.
CREATE FUNCTION core.fn_audit_kyc_document_view(p_actor uuid, p_document_id uuid)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role;
BEGIN
    SELECT role INTO v_role FROM core.users WHERE id = p_actor AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('reviewer', 'admin') THEN
        RAISE EXCEPTION 'only active staff can view KYC documents' USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM core.fn_audit(p_actor, 'kyc.document_viewed', 'kyc_documents', p_document_id::text);
END $$;

-- =============================================================================
-- 8c. SMALL ADDITIONS NEEDED BY THE BACKEND (still no table rights for any service role)
-- =============================================================================

-- A signed-in donor's own leaderboard preference (true until they say otherwise).
CREATE VIEW api.my_leaderboard_pref AS
SELECT COALESCE((SELECT l.show_publicly FROM core.leaderboard l WHERE l.user_id = core.current_user_id()), true) AS show_publicly
 WHERE core.current_user_id() IS NOT NULL;

-- The recipient's own payout destination, still encrypted (the API decrypts and masks it).
CREATE FUNCTION api.fn_my_payout()
RETURNS TABLE (receiver_type core.paypal_receiver_type, receiver_enc bytea)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT r.paypal_receiver_type, r.paypal_receiver_enc FROM core.recipients r WHERE r.user_id = core.current_user_id() $$;

-- Capture finalisation: find the donation an approved PayPal order belongs to. Returns no donor identity.
CREATE FUNCTION core.fn_donation_by_order(p_order_id text)
RETURNS TABLE (donation_id uuid, is_anonymous boolean, amount_cents bigint, donation_status core.donation_status)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$ SELECT d.id, d.is_anonymous, d.amount_cents, d.status FROM core.donations d WHERE d.paypal_order_id = p_order_id $$;

-- A refund of a captured gift. The donation trigger refuses it once the payout has left the queue,
-- in which case the webhook is recorded as failed and a human decides (money already moved).
CREATE FUNCTION core.fn_apply_capture_refund(p_capture_id text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    UPDATE core.donations SET status = 'refunded' WHERE paypal_capture_id = p_capture_id AND status = 'captured';
    RETURN FOUND;
END $$;

-- Webhooks that were recorded but not fully processed (crash, transient error). The reconciler retries them.
CREATE FUNCTION core.fn_list_retryable_webhooks(p_limit integer DEFAULT 50)
RETURNS TABLE (paypal_event_id text, event_type text, payload jsonb)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT w.paypal_event_id, w.event_type, w.payload
      FROM core.webhook_events w
     WHERE w.status IN ('received', 'failed')
       AND w.received_at < now() - interval '1 minute'
       AND w.received_at > now() - interval '24 hours'
     ORDER BY w.received_at
     LIMIT LEAST(GREATEST(p_limit, 1), 500)
$$;

-- Leaderboard preference can be set before the first gift.
CREATE OR REPLACE FUNCTION api.fn_set_leaderboard_visibility(p_show boolean)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
BEGIN
    IF core.current_user_id() IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    INSERT INTO core.leaderboard (user_id, show_publicly) VALUES (core.current_user_id(), p_show)
    ON CONFLICT (user_id) DO UPDATE SET show_publicly = EXCLUDED.show_publicly, updated_at = now();
END $$;

-- =============================================================================
-- 9. GRANTS
-- =============================================================================

-- Web API: views and functions in schema api. No table access of any kind.
GRANT SELECT ON api.public_campaigns, api.public_campaign_updates, api.public_campaign_comments,
                api.public_donation_feed, api.public_leaderboard, api.public_gratitude_wall, api.public_impact_stats,
                api.my_donations, api.my_pledge, api.my_gratitude, api.my_recipient_profile, api.my_campaign,
                api.my_leaderboard_pref
    TO sadqah_api;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA api TO sadqah_api;
-- Postgres checks function privileges in a view against the CALLER, so the my_* views need this one
-- harmless helper (it only echoes the per-request session setting).
GRANT EXECUTE ON FUNCTION core.current_user_id() TO sadqah_api;

-- Payout worker: batch lifecycle only.
GRANT EXECUTE ON FUNCTION
    core.fn_claim_payout_batch(integer, text), core.fn_get_batch_items(uuid), core.fn_get_batch(uuid),
    core.fn_claim_due_batch(), core.fn_mark_batch_submitted(uuid, text),
    core.fn_batch_submission_failed(uuid, text, boolean, integer),
    core.fn_expire_stale_donations(interval), core.fn_list_stale_batches(interval),
    core.fn_apply_payout_item_event(text, core.payout_item_status, text, text, text, text),
    core.fn_apply_batch_event(text, text, core.batch_status, text),
    core.fn_payout_queue_stats()
    TO sadqah_worker;

-- Webhook handler: inbox, capture, and reconciliation.
GRANT EXECUTE ON FUNCTION
    core.fn_record_webhook(text, text, text, jsonb), core.fn_finish_webhook(text, core.webhook_status, text),
    core.fn_mark_donation_captured(uuid, text, bigint, bytea),
    core.fn_apply_payout_item_event(text, core.payout_item_status, text, text, text, text),
    core.fn_apply_batch_event(text, text, core.batch_status, text),
    core.fn_donation_by_order(text), core.fn_apply_capture_refund(text), core.fn_list_retryable_webhooks(integer)
    TO sadqah_webhook;

-- KYC pipeline: read encrypted records, store advisory results.
GRANT SELECT ON core.recipients_kyc, core.kyc_documents TO sadqah_kyc;
GRANT UPDATE (scan_status) ON core.kyc_documents TO sadqah_kyc;
GRANT EXECUTE ON FUNCTION
    core.fn_store_kyc_assessment(uuid, bigint, numeric, numeric, jsonb, bigint, text),
    core.fn_kyc_case_context(uuid)
    TO sadqah_kyc;
CREATE POLICY kycdocs_scan_update ON core.kyc_documents FOR UPDATE TO sadqah_kyc USING (true) WITH CHECK (true);

-- Staff tools: read-only views, plus audited decision functions.
GRANT SELECT ON core.recipients_kyc, core.kyc_documents TO sadqah_admin;
GRANT SELECT ON core.v_admin_payout_queue, core.v_admin_batches, core.v_admin_ledger, core.v_admin_reconciliation,
                core.v_admin_kyc_queue, core.v_admin_message_queue, core.v_admin_gratitude_queue
    TO sadqah_admin;
GRANT EXECUTE ON FUNCTION
    core.fn_review_kyc(uuid, core.kyc_status, bigint, bigint, uuid, text),
    core.fn_moderate_message(uuid, core.moderation_status, text, uuid),
    core.fn_moderate_gratitude(uuid, core.moderation_status, uuid),
    core.fn_requeue_payout(uuid, uuid),
    core.fn_audit_kyc_document_view(uuid, uuid)
    TO sadqah_admin;

COMMIT;

RESET ROLE;
