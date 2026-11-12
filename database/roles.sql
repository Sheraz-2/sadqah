-- =============================================================================
-- SadQah | database/roles.sql
-- Run ONCE per cluster, as a superuser, BEFORE schema.sql.
--
--   psql -v ON_ERROR_STOP=1 \
--        -v api_password="$DB_API_PASSWORD" \
--        -v worker_password="$DB_WORKER_PASSWORD" \
--        -v webhook_password="$DB_WEBHOOK_PASSWORD" \
--        -v kyc_password="$DB_KYC_PASSWORD" \
--        -v admin_password="$DB_ADMIN_PASSWORD" \
--        -d sadqah -f database/roles.sql
--
-- Privilege model (least privilege, one login role per service):
--   sadqah_owner    NOLOGIN. Owns every object. SECURITY DEFINER functions run as
--                   this role, so they can reach private tables on behalf of callers.
--   sadqah_api      Public/donor/recipient web API. NO access to donations, payer data,
--                   messages or the payout queue. Reaches them only through api.* views
--                   and functions that mask or authorise.
--   sadqah_worker   Payout worker. EXECUTE on batch-claim functions only. Never sees donors.
--   sadqah_webhook  PayPal webhook handler. EXECUTE on reconciliation functions only.
--   sadqah_kyc      KYC/AI pipeline. Reads KYC documents, writes assessments.
--   sadqah_admin    Staff tools (reviewers, moderators, compliance). Reads admin views.
-- =============================================================================

-- Group role that owns everything -------------------------------------------------
SELECT 'CREATE ROLE sadqah_owner NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sadqah_owner') \gexec

-- Login roles: passwords come from psql variables, never from this file ------------
SELECT format('CREATE ROLE sadqah_api LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 100 PASSWORD %L', :'api_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sadqah_api') \gexec

SELECT format('CREATE ROLE sadqah_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 10 PASSWORD %L', :'worker_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sadqah_worker') \gexec

SELECT format('CREATE ROLE sadqah_webhook LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 20 PASSWORD %L', :'webhook_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sadqah_webhook') \gexec

SELECT format('CREATE ROLE sadqah_kyc LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 10 PASSWORD %L', :'kyc_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sadqah_kyc') \gexec

SELECT format('CREATE ROLE sadqah_admin LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 20 PASSWORD %L', :'admin_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sadqah_admin') \gexec

-- The owner needs to create schemas in this database -------------------------------
SELECT format('GRANT CREATE ON DATABASE %I TO sadqah_owner', current_database()) \gexec

-- Nobody gets anything by accident ----------------------------------------------------
REVOKE ALL ON SCHEMA public FROM PUBLIC;
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO sadqah_owner, sadqah_api, sadqah_worker, sadqah_webhook, sadqah_kyc, sadqah_admin', current_database()) \gexec
