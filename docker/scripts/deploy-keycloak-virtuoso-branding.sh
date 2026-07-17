#!/usr/bin/env bash
# Deploy Keycloak login themes: variphi → gateway KC, virtuoso → keycloak-virtuoso.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VARIPHI_THEME="${SCRIPT_DIR}/../keycloak-theme/variphi"
VIRTUOSO_THEME="${SCRIPT_DIR}/../keycloak-theme/virtuoso"
GATEWAY_HOST="${GATEWAY_HOST:-43.204.247.12}"
GATEWAY_USER="${GATEWAY_USER:-ubuntu}"
VARIPHI_REMOTE="/home/ubuntu/vgi-microservices/keycloak/themes/variphi"
VIRTUOSO_REMOTE="/home/ubuntu/keycloak-virtuoso/themes/virtuoso"

SSH_KEY="${SSH_KEY:-}"
for candidate in "${HOME}/.ssh/microserive-prod.pem" "${HOME}/microserive-prod.pem"; do
  if [[ -z "${SSH_KEY}" && -f "${candidate}" ]]; then
    SSH_KEY="${candidate}"
  fi
done
if [[ -z "${SSH_KEY}" || ! -f "${SSH_KEY}" ]]; then
  echo "ERROR: SSH key not found (set SSH_KEY or place microserive-prod.pem in ~/.ssh/)" >&2
  exit 1
fi

SSH_OPTS=(-i "${SSH_KEY}" -o StrictHostKeyChecking=no -o ConnectTimeout=15)

deploy_theme() {
  local src="$1" remote="$2" container="$3" label="$4"
  if [[ ! -d "${src}/login" ]]; then
    echo "ERROR: theme source missing at ${src}/login" >&2
    exit 1
  fi
  local staging="/tmp/kc-theme-${label}-$$"
  echo "==> Syncing ${label} theme to ${remote}"
  ssh "${SSH_OPTS[@]}" "${GATEWAY_USER}@${GATEWAY_HOST}" "rm -rf '${staging}' && mkdir -p '${staging}'"
  rsync -avz -e "ssh ${SSH_OPTS[*]}" "${src}/" "${GATEWAY_USER}@${GATEWAY_HOST}:${staging}/"
  ssh "${SSH_OPTS[@]}" "${GATEWAY_USER}@${GATEWAY_HOST}" \
    "sudo mkdir -p '${remote}' && sudo rsync -a --delete '${staging}/' '${remote}/' && rm -rf '${staging}'"
  echo "==> Restarting ${container}"
  ssh "${SSH_OPTS[@]}" "${GATEWAY_USER}@${GATEWAY_HOST}" \
    "docker restart '${container}' && sleep 5 && docker ps --filter name='${container}' --format '{{.Names}} {{.Status}}'"
}

deploy_theme "${VARIPHI_THEME}" "${VARIPHI_REMOTE}" "keycloak" "variphi"
deploy_theme "${VIRTUOSO_THEME}" "${VIRTUOSO_REMOTE}" "keycloak-virtuoso" "virtuoso"

echo "==> Themes deployed (variphi on gateway KC, virtuoso on keycloak-virtuoso)"
