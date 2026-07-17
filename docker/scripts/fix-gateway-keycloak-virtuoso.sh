#!/usr/bin/env bash
# Configure Keycloak thingsboard client for Virtuoso NetSoft only (viot.virtuosonetsoft.com).
set -euo pipefail

VIOT_BASE="https://viot.virtuosonetsoft.com"
REDIRECT_EXACT="${VIOT_BASE}/login/oauth2/code/"
REDIRECT_WILD="${VIOT_BASE}/login/oauth2/code/*"
POST_LOGOUT_URIS="${VIOT_BASE}/*##${VIOT_BASE}/oauth2/authorization/*"

REALM="things"
CLIENT="thingsboard"

MS_DIR="${VG_MICROSERVICES_DIR:-/var/vgi-microservices}"
if [[ ! -d "${MS_DIR}" ]]; then
  for d in /var/vgi-microservices /home/ubuntu/vgi-microservices /opt/vgi-microservices; do
    if [[ -d "$d" ]]; then MS_DIR="$d"; break; fi
  done
fi

KC_CONTAINER="$(docker ps --format '{{.Names}}' | grep -i keycloak | head -1 || true)"
if [[ -z "${KC_CONTAINER}" ]]; then
  echo "ERROR: no Keycloak container running" >&2
  exit 1
fi
echo "Keycloak container: ${KC_CONTAINER}"

docker exec "${KC_CONTAINER}" bash -c "
  set -e
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://127.0.0.1:8080/auth \
    --realm master \
    --user \"\${KEYCLOAK_ADMIN:-admin}\" \
    --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\" 2>/dev/null || \
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://127.0.0.1:8080 \
    --realm master \
    --user \"\${KEYCLOAK_ADMIN:-admin}\" \
    --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\"

  CID=\$(/opt/keycloak/bin/kcadm.sh get clients -r ${REALM} -q clientId=${CLIENT} --fields id --format csv --noquotes | tail -1)

  /opt/keycloak/bin/kcadm.sh update \"clients/\${CID}\" -r ${REALM} \
    -s enabled=true \
    -s standardFlowEnabled=true \
    -s 'redirectUris=[\"${REDIRECT_EXACT}\",\"${REDIRECT_WILD}\",\"http://localhost:8080/login/oauth2/code/*\",\"http://localhost:9090/login/oauth2/code/*\",\"http://localhost:9091/login/oauth2/code/*\"]' \
    -s 'webOrigins=[\"${VIOT_BASE}\",\"https://*.virtuosonetsoft.com\",\"http://localhost:8080\",\"http://localhost:9090\",\"http://localhost:9091\"]' \
    -s 'attributes.\"post.logout.redirect.uris\"=\"${POST_LOGOUT_URIS}\"' \
    -s 'baseUrl=${VIOT_BASE}'

  echo \"Client \${CID} updated (Virtuoso-only URIs + post.logout.redirect.uris)\"
"

if [[ -f "${MS_DIR}/docker-compose.yml" ]]; then
  (cd "${MS_DIR}" && docker compose restart keycloak) || docker restart "${KC_CONTAINER}"
else
  docker restart "${KC_CONTAINER}"
fi

sleep 15
echo "OK: Virtuoso NetSoft Keycloak client configured (variphi.com URIs removed)"
