#!/usr/bin/env bash
# Start Variphi ThingsBoard SSO stack with production env from variphi-sso.env.
set -euo pipefail
cd "$(dirname "$0")"
set -a
source variphi-sso.env
set +a
exec docker compose -f docker-compose.variphi-sso.yml "$@"
