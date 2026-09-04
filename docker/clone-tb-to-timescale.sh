#!/usr/bin/env bash
# Clone a ThingsBoard SQL-mode database to a TimescaleDB target and convert telemetry tables.
set -euo pipefail

SOURCE_DB="${1:?source database name (e.g. tb)}"
TARGET_DB="${2:?target database name (e.g. tb_timescale)}"
PGHOST="${DATABASE_HOST:-13.206.196.162}"
PGPORT="${DATABASE_PORT:-5432}"
PGUSER="${DATABASE_USER:-variphi}"
export PGPASSWORD="${DATABASE_PASSWORD:-vgi@2026}"

WORKDIR="${TMPDIR:-/tmp}/tb-timescale-migrate-$$"
mkdir -p "$WORKDIR"
DUMP_FILE="$WORKDIR/${SOURCE_DB}.dump"

cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

echo "==> Dumping ${SOURCE_DB} from ${PGHOST}:${PGPORT}"
pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -Fc -d "$SOURCE_DB" -f "$DUMP_FILE"

echo "==> Recreating ${TARGET_DB}"
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '${TARGET_DB}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS ${TARGET_DB};
CREATE DATABASE ${TARGET_DB} OWNER ${PGUSER};
SQL

echo "==> Restoring into ${TARGET_DB}"
pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET_DB" --no-owner --no-privileges "$DUMP_FILE"

echo "==> Converting telemetry tables to Timescale hypertable"
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET_DB" -v ON_ERROR_STOP=1 \
  -f "$(dirname "$0")/migrate-sql-to-timescale.sql"

echo "==> Validation counts for ${TARGET_DB}"
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$TARGET_DB" -c "
SELECT 'ts_kv' AS tbl, COUNT(*) FROM ts_kv
UNION ALL SELECT 'ts_kv_latest', COUNT(*) FROM ts_kv_latest
UNION ALL SELECT 'device', COUNT(*) FROM device;
SELECT hypertable_name, num_chunks
FROM timescaledb_information.hypertables
WHERE hypertable_name = 'ts_kv';
"

echo "==> Done: ${SOURCE_DB} -> ${TARGET_DB}"
