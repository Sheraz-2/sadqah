-- =============================================================================
-- Patch 002: password recovery by one-time code (self-service, and admin-initiated).
--
-- Additive and idempotent: safe to run more than once, never drops, rewrites or resets existing data.
-- The patch adds one table and five functions, and replaces one existing function (api.fn_set_my_password_hash, from patch 001)
-- so that a normal password change also closes any recovery code still outstanding. Locking order everywhere is: the users
-- row first, then the password_resets row, so concurrent requests queue up instead of failing or deadlocking. Codes are never stored: only an HMAC of the code, made with a
-- server secret, so a stolen database cannot be used to read or replay codes.
-- Applied automatically on a FRESH database by `docker compose up` (db-init). On an EXISTING database run:
--   Get-Content database\patches\002_password_recovery.sql | docker compose exec -T db psql -U postgres -d sadqah -v ON_ERROR_STOP=1
-- =============================================================================

SET ROLE sadqah_owner;

BEGIN;

-- ---- 1. one row per issued code -------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.password_resets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES core.users(id) ON DELETE RESTRICT,
    code_hmac       bytea NOT NULL CHECK (octet_length(code_hmac) = 32),   -- HMAC-SHA256 keyed with a server secret
    channel         text NOT NULL DEFAULT 'email' CHECK (channel IN ('email', 'sms')),
    initiated_by    uuid REFERENCES core.users(id) ON DELETE RESTRICT,     -- the admin, for admin-initiated resets
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    attempts        integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts    integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 10),
    consumed_at     timestamptz,                                           -- set once, on success: a code works one time
    invalidated_at  timestamptz,                                           -- replaced by a newer code, locked out, expired or undeliverable
    CONSTRAINT password_resets_expiry CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS idx_pw_resets_user ON core.password_resets (user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pw_resets_one_open ON core.password_resets (user_id)
    WHERE consumed_at IS NULL AND invalidated_at IS NULL;
ALTER TABLE core.password_resets ENABLE ROW LEVEL SECURITY;   -- no policy: only the SECURITY DEFINER functions below touch it
REVOKE ALL ON core.password_resets FROM PUBLIC;

-- ---- 2. self-service: issue a code ---------------------------------------------------------------------------------------
-- Returns one row only when a code was actually issued (and so must be sent). Unknown, inactive or throttled accounts return no
-- rows, and the caller answers the same generic message either way. The 60 second cooldown and the hourly cap live here as well
-- as in the web tier, so they still hold if the rate limiter's Redis is down.
CREATE OR REPLACE FUNCTION api.fn_pr_start(p_email_blind bytea, p_code_hmac bytea, p_ttl_seconds integer, p_channel text DEFAULT 'email')
RETURNS TABLE (reset_id uuid, email_ct bytea, phone_ct bytea)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_uid uuid; v_email bytea; v_phone bytea; v_phone_ok boolean; v_id uuid;
BEGIN
    IF p_channel NOT IN ('email', 'sms') THEN
        RAISE EXCEPTION 'unknown channel' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_ttl_seconds NOT BETWEEN 60 AND 3600 OR p_code_hmac IS NULL OR octet_length(p_code_hmac) <> 32 THEN
        RAISE EXCEPTION 'bad recovery parameters' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT u.id, u.email_enc, u.phone_enc, (u.phone_verified_at IS NOT NULL AND u.phone_enc IS NOT NULL)
      INTO v_uid, v_email, v_phone, v_phone_ok
      FROM core.users u WHERE u.email_blind_idx = p_email_blind AND u.is_active
       FOR NO KEY UPDATE OF u;   -- one issuer at a time per person: a concurrent request waits here, then sees this one's row below
    IF v_uid IS NULL THEN RETURN; END IF;
    IF p_channel = 'sms' AND NOT v_phone_ok THEN RETURN; END IF;
    IF EXISTS (SELECT 1 FROM core.password_resets r WHERE r.user_id = v_uid AND r.created_at > now() - interval '60 seconds') THEN RETURN; END IF;
    IF (SELECT count(*) FROM core.password_resets r WHERE r.user_id = v_uid AND r.created_at > now() - interval '1 hour') >= 5 THEN RETURN; END IF;

    UPDATE core.password_resets r SET invalidated_at = now()
     WHERE r.user_id = v_uid AND r.consumed_at IS NULL AND r.invalidated_at IS NULL;
    INSERT INTO core.password_resets (user_id, code_hmac, channel, expires_at)
    VALUES (v_uid, p_code_hmac, p_channel, now() + make_interval(secs => p_ttl_seconds))
    RETURNING id INTO v_id;
    PERFORM core.fn_audit(v_uid, 'password_reset.requested', 'users', v_uid::text, jsonb_build_object('channel', p_channel, 'by', 'self'));
    RETURN QUERY SELECT v_id, v_email, v_phone;
END $$;

-- ---- 3. redeem a code and set the new password ---------------------------------------------------------------------------
-- One atomic step under a row lock: a wrong code costs one of the code's attempts (the code dies after max_attempts), an expired
-- code dies, and a right code is consumed and changes the password in the same transaction. Returns FALSE for every failure, with
-- no hint as to why, and nothing for an unknown e-mail. A right code sent by e-mail also proves the person controls that inbox, so
-- e-mail is marked verified.
CREATE OR REPLACE FUNCTION api.fn_pr_redeem(p_email_blind bytea, p_code_hmac bytea, p_new_hash text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_uid uuid; v_id uuid; v_hmac bytea; v_exp timestamptz; v_attempts integer; v_max integer; v_channel text;
BEGIN
    IF p_new_hash IS NULL OR p_new_hash = '' OR p_code_hmac IS NULL OR octet_length(p_code_hmac) <> 32 THEN
        RETURN false;
    END IF;
    SELECT u.id INTO v_uid FROM core.users u
     WHERE u.email_blind_idx = p_email_blind AND u.is_active
       FOR NO KEY UPDATE OF u;   -- same lock order as issuing a code (users, then the code row): no deadlock
    IF v_uid IS NULL THEN RETURN false; END IF;
    SELECT r.id, r.code_hmac, r.expires_at, r.attempts, r.max_attempts, r.channel
      INTO v_id, v_hmac, v_exp, v_attempts, v_max, v_channel
      FROM core.password_resets r
     WHERE r.user_id = v_uid AND r.consumed_at IS NULL AND r.invalidated_at IS NULL
       FOR UPDATE OF r;
    IF v_id IS NULL THEN RETURN false; END IF;
    IF v_exp <= now() OR v_attempts >= v_max THEN
        UPDATE core.password_resets SET invalidated_at = now() WHERE id = v_id;
        RETURN false;
    END IF;
    IF v_hmac <> p_code_hmac THEN   -- both sides are keyed HMAC outputs: a caller cannot steer the comparison
        UPDATE core.password_resets SET attempts = attempts + 1,
               invalidated_at = CASE WHEN attempts + 1 >= max_attempts THEN now() ELSE NULL END
         WHERE id = v_id;
        IF v_attempts + 1 >= v_max THEN
            PERFORM core.fn_audit(v_uid, 'password_reset.locked_out', 'users', v_uid::text, '{}'::jsonb);
        END IF;
        RETURN false;
    END IF;
    UPDATE core.password_resets SET consumed_at = now(), attempts = attempts + 1 WHERE id = v_id;
    UPDATE core.users
       SET password_hash = p_new_hash, failed_login_count = 0, locked_until = NULL,
           email_verified_at = CASE WHEN v_channel = 'email' THEN COALESCE(email_verified_at, now()) ELSE email_verified_at END,
           phone_verified_at = CASE WHEN v_channel = 'sms' THEN COALESCE(phone_verified_at, now()) ELSE phone_verified_at END
     WHERE id = v_uid;
    PERFORM core.fn_audit(v_uid, 'password_reset.completed', 'users', v_uid::text, '{}'::jsonb);
    RETURN true;
END $$;

-- ---- 4. e-mail could not be sent: the code is useless, so close it (and say so in the audit log) ---------------------------------
CREATE OR REPLACE FUNCTION core.fn_pr_delivery_failed(p_reset_id uuid, p_reason text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_uid uuid;
BEGIN
    UPDATE core.password_resets SET invalidated_at = now()
     WHERE id = p_reset_id AND consumed_at IS NULL AND invalidated_at IS NULL
     RETURNING user_id INTO v_uid;
    IF v_uid IS NOT NULL THEN
        PERFORM core.fn_audit(NULL, 'password_reset.delivery_failed', 'users', v_uid::text,
                              jsonb_build_object('reason', left(COALESCE(p_reason, 'unknown'), 40)));
    END IF;
END $$;

CREATE OR REPLACE FUNCTION api.fn_pr_delivery_failed(p_reset_id uuid, p_reason text)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$ SELECT core.fn_pr_delivery_failed(p_reset_id, p_reason) $$;

-- ---- 5. admin-initiated: an administrator asks for a code to be sent to the person --------------------------------------------
-- Admin only (checked here as well as in the web tier). The code goes ONLY to the e-mail address on record, and only when that
-- address is verified; the administrator never sees the code, the e-mail or the password. Administrators cannot be targeted
-- (they use the normal "forgot password" flow) and nobody can target themselves. Every attempt is audited, none with secrets.
-- outcome: created | no_eligible_account | too_soon
CREATE OR REPLACE FUNCTION core.fn_admin_start_reset(p_admin uuid, p_email_blind bytea, p_code_hmac bytea, p_ttl_seconds integer)
RETURNS TABLE (outcome text, reset_id uuid, email_ct bytea)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_role core.user_role; v_uid uuid; v_email bytea; v_trole core.user_role; v_verified boolean; v_id uuid;
BEGIN
    -- The caller must BE the administrator it names: the web tier opens this transaction as that user, so a mismatch means a bug
    -- or a forged argument, and is refused rather than audited under somebody else's name.
    IF p_admin IS NULL OR core.current_user_id() IS DISTINCT FROM p_admin THEN
        RAISE EXCEPTION 'administrator does not match the signed-in user' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT u.role INTO v_role FROM core.users u WHERE u.id = p_admin AND u.is_active;
    IF v_role IS DISTINCT FROM 'admin' THEN
        RAISE EXCEPTION 'only an active administrator can start a password reset' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_ttl_seconds NOT BETWEEN 60 AND 3600 OR p_code_hmac IS NULL OR octet_length(p_code_hmac) <> 32 THEN
        RAISE EXCEPTION 'bad recovery parameters' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT u.id, u.email_enc, u.role, (u.email_verified_at IS NOT NULL)
      INTO v_uid, v_email, v_trole, v_verified
      FROM core.users u WHERE u.email_blind_idx = p_email_blind AND u.is_active
       FOR NO KEY UPDATE OF u;   -- serialises with self-service requests, password changes and redemptions for this person
    IF v_uid IS NULL OR NOT v_verified OR v_trole = 'admin' OR v_uid = p_admin THEN
        PERFORM core.fn_audit(p_admin, 'password_reset.admin_no_eligible_account', 'users', NULL, '{}'::jsonb);
        RETURN QUERY SELECT 'no_eligible_account'::text, NULL::uuid, NULL::bytea;
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM core.password_resets r WHERE r.user_id = v_uid AND r.created_at > now() - interval '60 seconds')
       OR (SELECT count(*) FROM core.password_resets r WHERE r.user_id = v_uid AND r.created_at > now() - interval '1 hour') >= 5 THEN
        PERFORM core.fn_audit(p_admin, 'password_reset.admin_too_soon', 'users', v_uid::text, '{}'::jsonb);
        RETURN QUERY SELECT 'too_soon'::text, NULL::uuid, NULL::bytea;
        RETURN;
    END IF;
    UPDATE core.password_resets r SET invalidated_at = now()
     WHERE r.user_id = v_uid AND r.consumed_at IS NULL AND r.invalidated_at IS NULL;
    INSERT INTO core.password_resets (user_id, code_hmac, channel, initiated_by, expires_at)
    VALUES (v_uid, p_code_hmac, 'email', p_admin, now() + make_interval(secs => p_ttl_seconds))
    RETURNING id INTO v_id;
    PERFORM core.fn_audit(p_admin, 'password_reset.admin_initiated', 'users', v_uid::text, jsonb_build_object('channel', 'email'));
    RETURN QUERY SELECT 'created'::text, v_id, v_email;
END $$;

-- ---- 6. a normal password change closes outstanding recovery codes ----------------------------------------------------------------
-- Replaces the patch-001 definition: identical signature, checks and behaviour, plus: any recovery code still open for this person
-- is closed (they just proved they know the current password, so a code mailed earlier must not remain a second way in), and the
-- audit row says so. The users row is updated first, which also takes the per-person lock used by the functions above.
CREATE OR REPLACE FUNCTION api.fn_set_my_password_hash(p_hash text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_closed integer;
BEGIN
    IF core.current_user_id() IS NULL THEN
        RAISE EXCEPTION 'authentication required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE core.users SET password_hash = p_hash, failed_login_count = 0, locked_until = NULL
     WHERE id = core.current_user_id() AND is_active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'account not found' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    UPDATE core.password_resets SET invalidated_at = now()
     WHERE user_id = core.current_user_id() AND consumed_at IS NULL AND invalidated_at IS NULL;
    GET DIAGNOSTICS v_closed = ROW_COUNT;
    PERFORM core.fn_audit(core.current_user_id(), 'account.password_changed', 'users', core.current_user_id()::text,
                          CASE WHEN v_closed > 0 THEN jsonb_build_object('recovery_codes_closed', v_closed) ELSE '{}'::jsonb END);
END $$;

-- ---- 7. grants -----------------------------------------------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION
    api.fn_pr_start(bytea, bytea, integer, text), api.fn_pr_redeem(bytea, bytea, text), api.fn_pr_delivery_failed(uuid, text),
    api.fn_set_my_password_hash(text)
    TO sadqah_api;
GRANT EXECUTE ON FUNCTION
    core.fn_admin_start_reset(uuid, bytea, bytea, integer), core.fn_pr_delivery_failed(uuid, text)
    TO sadqah_admin;

COMMIT;

RESET ROLE;
