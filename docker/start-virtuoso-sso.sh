#!/usr/bin/env bash
# Start Virtuoso NetSoft ThingsBoard SSO stack with production env from virtuoso-sso.env.
set -euo pipefail
cd "$(dirname "$0")"
set -a
source virtuoso-sso.env
set +a
exec docker compose -p virtuoso-tb -f docker-compose.virtuoso-sso.yml "$@"
