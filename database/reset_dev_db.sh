#!/usr/bin/env bash
# Rebuilds a throwaway development database from scratch (roles + schema).
# Usage: PGHOST=... PGUSER=postgres database/reset_dev_db.sh [dbname]
set -euo pipefail
DB="${1:-sadqah}"
HERE="$(cd "$(dirname "$0")" && pwd)"
psql -q -v ON_ERROR_STOP=1 -d postgres -c "DROP DATABASE IF EXISTS \"$DB\"" -c "CREATE DATABASE \"$DB\""
psql -q -v ON_ERROR_STOP=1 -d "$DB" \
  -v api_password="${DB_API_PASSWORD:-restored_api_pw}" -v worker_password="${DB_WORKER_PASSWORD:-restored_worker_pw}" \
  -v webhook_password="${DB_WEBHOOK_PASSWORD:-restored_hook_pw}" -v kyc_password="${DB_KYC_PASSWORD:-restored_kyc_pw}" \
  -v admin_password="${DB_ADMIN_PASSWORD:-restored_admin_pw}" -f "$HERE/roles.sql"
psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$HERE/schema.sql"
# Optional additive SQL (CREATE OR REPLACE ... only) that feature work adds without touching schema.sql.
for patch in "$HERE"/patches/*.sql; do
  [ -e "$patch" ] || continue
  psql -q -v ON_ERROR_STOP=1 -d "$DB" -f "$patch"
done
echo "database '$DB' rebuilt"
