#!/usr/bin/env bash
# Run from viot host (65.0.246.152) after copying the gateway PEM:
#   scp -i microserive-prod.pem microserive-prod.pem ubuntu@65.0.246.152:~/.ssh/
#   chmod 600 ~/.ssh/microserive-prod.pem
#   ./run-gateway-keycloak-fix.sh

set -euo pipefail

GATEWAY="ubuntu@43.204.247.12"
KEY="${GATEWAY_PEM:-${HOME}/.ssh/microserive-prod.pem}"
if [[ ! -f "${KEY}" && -f "${HOME}/microserive-prod.pem" ]]; then
  KEY="${HOME}/microserive-prod.pem"
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "${KEY}" ]]; then
  echo "Missing ${KEY}" >&2
  echo "From your Mac:" >&2
  echo "  scp -i /Users/akashkumar/Desktop/var/pem/prod/microserive-prod.pem \\" >&2
  echo "      /Users/akashkumar/Desktop/var/pem/prod/microserive-prod.pem \\" >&2
  echo "      ubuntu@65.0.246.152:~/.ssh/microserive-prod.pem" >&2
  exit 1
fi
chmod 600 "${KEY}"

ssh -i "${KEY}" -o StrictHostKeyChecking=accept-new "${GATEWAY}" 'bash -s' < "${SCRIPT_DIR}/fix-gateway-keycloak.sh"
