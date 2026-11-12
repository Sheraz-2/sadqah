-- =============================================================================
-- Patch 003: private message threads for signed-in donors who gave PUBLICLY.
--
-- Anonymous gifts keep reading and writing their thread with the Donation Token (api.fn_track_thread, fn_donor_post_message,
-- fn_donor_mark_read: untouched). A public gift has a donor_user_id and no token, so the donor had no way in. These four functions
-- are the same door, opened by the signed-in identity instead of a token. The same table (core.anonymous_messages), the same
-- encryption (the application binds each body to its donation id), the same trigger (messages only on delivered gifts), the same
-- limit (10 per sender per donation per 24 hours) and the same moderation: nothing is copied or bypassed.
--
-- Ownership is always `d.donor_user_id = core.current_user_id() AND NOT d.is_anonymous`, read from the per-request session setting.
-- No user id is ever a parameter. A donation that is not yours, does not exist, or is anonymous gives zero rows (read) or the same
-- "thread not found" error as a missing thread (write), so nothing is revealed about it.
-- Additive and idempotent: adds four functions and one grant list; no table, view, policy or data is touched.
-- Applied automatically on a FRESH database by `docker compose up` (db-init). On an EXISTING database run:
--   Get-Content database\patches\003_donor_threads.sql | docker compose exec -T db psql -U postgres -d sadqah -v ON_ERROR_STOP=1
-- =============================================================================

SET ROLE sadqah_owner;

BEGIN;

-- ---- 1. the donor's conversations: captured and delivered public gifts only (initiated, failed, cancelled and refunded are not listed)
CREATE OR REPLACE FUNCTION api.fn_my_threads()
RETURNS TABLE (donation_id uuid, campaign_slug text, campaign_title text, recipient_name text, donation_status core.donation_status,
               thread_open boolean, paid_out_at timestamptz, last_message_at timestamptz, unread_count bigint)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT d.id, c.slug, c.title, r.public_name, d.status, (d.status = 'paid_out'), d.paid_out_at,
           max(m.created_at) FILTER (WHERE m.sender = 'donor' OR m.moderation_status = 'approved'),
           count(m.id) FILTER (WHERE m.sender = 'recipient' AND m.moderation_status = 'approved' AND m.read_by_donor_at IS NULL)
      FROM core.donations d
      JOIN core.campaigns c  ON c.id = d.campaign_id
      JOIN core.recipients r ON r.id = d.recipient_id
      LEFT JOIN core.anonymous_messages m ON m.donation_id = d.id
     WHERE d.donor_user_id = core.current_user_id() AND NOT d.is_anonymous AND d.status IN ('captured', 'paid_out')
     GROUP BY d.id, c.id, r.id
     ORDER BY d.created_at DESC
$$;

-- ---- 2. one conversation: the donor's own messages in any status, the recipient's only once approved -------------------------
CREATE OR REPLACE FUNCTION api.fn_my_thread_messages(p_donation_id uuid)
RETURNS TABLE (id uuid, sender core.message_sender, body_enc bytea, moderation_status core.moderation_status, created_at timestamptz)
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = core, pg_catalog
AS $$
    SELECT m.id, m.sender, m.body_enc, m.moderation_status, m.created_at
      FROM core.anonymous_messages m
      JOIN core.donations d ON d.id = m.donation_id
     WHERE m.donation_id = p_donation_id
       AND d.donor_user_id = core.current_user_id() AND NOT d.is_anonymous AND d.status IN ('captured', 'paid_out')
       AND (m.sender = 'donor' OR m.moderation_status = 'approved')
     ORDER BY m.created_at
$$;

-- ---- 3. send: same limit as the token door; the trigger core.trg_messages_before_insert still requires status 'paid_out' -------
-- The donation row is locked (FOR UPDATE) BEFORE the 24-hour count and held until the insert commits, so two concurrent sends for the same
-- donation queue up: the second one counts after the first has committed and sees its message. Without the lock both would count 9 and both insert.
-- The lock row is the donor's own, delivered, public donation, i.e. exactly the ownership rule of the other three functions.
CREATE OR REPLACE FUNCTION api.fn_my_post_message(p_donation_id uuid, p_body_enc bytea)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
DECLARE v_locked uuid; v_recent integer; v_id uuid;
BEGIN
    SELECT d.id INTO v_locked FROM core.donations d
     WHERE d.id = p_donation_id AND d.donor_user_id = core.current_user_id() AND NOT d.is_anonymous AND d.status = 'paid_out'
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'thread not found' USING ERRCODE = 'invalid_authorization_specification';
    END IF;
    SELECT count(*) INTO v_recent FROM core.anonymous_messages
     WHERE donation_id = p_donation_id AND sender = 'donor' AND created_at > now() - interval '24 hours';
    IF v_recent >= 10 THEN
        RAISE EXCEPTION 'message limit reached for today' USING ERRCODE = 'program_limit_exceeded';
    END IF;
    INSERT INTO core.anonymous_messages (donation_id, sender, body_enc)
    VALUES (p_donation_id, 'donor', p_body_enc) RETURNING id INTO v_id;
    RETURN v_id;
END $$;

-- ---- 4. reading approved recipient replies clears the donor's unread count ---------------------------------------------------
CREATE OR REPLACE FUNCTION api.fn_my_mark_read(p_donation_id uuid)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_catalog
AS $$
    UPDATE core.anonymous_messages m SET read_by_donor_at = now()
      FROM core.donations d
     WHERE d.id = m.donation_id AND m.donation_id = p_donation_id
       AND d.donor_user_id = core.current_user_id() AND NOT d.is_anonymous AND d.status IN ('captured', 'paid_out')
       AND m.sender = 'recipient' AND m.moderation_status = 'approved' AND m.read_by_donor_at IS NULL
$$;

-- ---- 5. grants (the blanket grant in schema.sql only covered functions that existed when it ran) ------------------------------
GRANT EXECUTE ON FUNCTION
    api.fn_my_threads(), api.fn_my_thread_messages(uuid), api.fn_my_post_message(uuid, bytea), api.fn_my_mark_read(uuid)
    TO sadqah_api;

COMMIT;
