#!/usr/bin/env bash
# Fix Keycloak on api.edge (vgi-microservices gateway) for ThingsBoard SSO.
# Run ON THE GATEWAY HOST (43.204.247.12) after SSH:
#   ssh -i microserive-prod.pem ubuntu@43.204.247.12
#   bash -s < fix-gateway-keycloak.sh
#
# Or from viot host once PEM is copied:
#   ssh -i /home/ubuntu/.ssh/microserive-prod.pem ubuntu@43.204.247.12 'bash -s' < fix-gateway-keycloak.sh

set -euo pipefail

VIOT_BASE="https://viot.variphi.com"
REDIRECT_EXACT="${VIOT_BASE}/login/oauth2/code/"
REDIRECT_WILD="${VIOT_BASE}/login/oauth2/code/*"
POST_LOGOUT="${VIOT_BASE}/*"
WEB_ORIGIN="${VIOT_BASE}"

MS_DIR="${VG_MICROSERVICES_DIR:-/var/vgi-microservices}"
REALM="things"
CLIENT="thingsboard"

echo "==> Looking for vgi-microservices at ${MS_DIR}"
if [[ ! -d "${MS_DIR}" ]]; then
  for d in /var/vgi-microservices /home/ubuntu/vgi-microservices /opt/vgi-microservices; do
    if [[ -d "$d" ]]; then MS_DIR="$d"; break; fi
  done
fi
if [[ ! -d "${MS_DIR}" ]]; then
  echo "ERROR: vgi-microservices not found. Set VG_MICROSERVICES_DIR." >&2
  exit 1
fi
echo "Using ${MS_DIR}"

KC_CONTAINER="$(docker ps --format '{{.Names}}' | grep -i keycloak | head -1 || true)"
if [[ -z "${KC_CONTAINER}" ]]; then
  echo "ERROR: no Keycloak container running" >&2
  docker ps
  exit 1
fi
echo "Keycloak container: ${KC_CONTAINER}"

# --- 1) Ensure redirect URIs in shared Postgres (idempotent) ---
if command -v docker >/dev/null 2>&1; then
  echo "==> Updating redirect_uris / web_origins in keycloak DB (if KC_DB_* set in compose)"
  # Optional: set KEYCLOAK_DB_HOST etc. from gateway .env before running
fi

# --- 2) kcadm on localhost inside Keycloak container ---
echo "==> Configuring client ${CLIENT} in realm ${REALM} via kcadm"
docker exec "${KC_CONTAINER}" bash -c '
  set -e
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://127.0.0.1:8080/auth \
    --realm master \
    --user "${KEYCLOAK_ADMIN:-admin}" \
    --password "${KEYCLOAK_ADMIN_PASSWORD:-admin}" 2>/dev/null || \
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://127.0.0.1:8080 \
    --realm master \
    --user "${KEYCLOAK_ADMIN:-admin}" \
    --password "${KEYCLOAK_ADMIN_PASSWORD:-admin}"

  CID=$(/opt/keycloak/bin/kcadm.sh get clients -r '"${REALM}"' -q clientId='"${CLIENT}"' --fields id --format csv --noquotes | tail -1)
  if [[ -z "$CID" || "$CID" == "id" ]]; then
    echo "Client '"${CLIENT}"' not found in realm '"${REALM}"'" >&2
    exit 1
  fi

  /opt/keycloak/bin/kcadm.sh update "clients/${CID}" -r '"${REALM}"' -s '"enabled=true"' -s '"standardFlowEnabled=true"' \
    -s '"redirectUris=[\"'"${REDIRECT_EXACT}"'\",\"'"${REDIRECT_WILD}"'\",\"http://localhost:8080/login/oauth2/code/*\",\"http://localhost:9090/login/oauth2/code/*\"]'" \
    -s '"webOrigins=[\"'"${WEB_ORIGIN}"'\",\"https://*.variphi.com\",\"http://localhost:8080\",\"http://localhost:9090\"]'" \
    -s '"baseUrl='"${VIOT_BASE}"'"'

  echo "Client updated: ${CID}"
'

# --- 3) Patch realm-export.json for future deploys ---
EXPORT="${MS_DIR}/keycloak/realm-export.json"
if [[ -f "${EXPORT}" ]]; then
  echo "==> Patching ${EXPORT} (thingsboard redirect URIs)"
  python3 - <<PY
import json, sys
path = "${EXPORT}"
with open(path) as f:
    data = json.load(f)
clients = data.get("clients") or []
for c in clients:
    if c.get("clientId") == "${CLIENT}":
        uris = set(c.get("redirectUris") or [])
        uris.update([
            "${REDIRECT_EXACT}",
            "${REDIRECT_WILD}",
            "http://localhost:8080/login/oauth2/code/*",
            "http://localhost:9090/login/oauth2/code/*",
        ])
        c["redirectUris"] = sorted(uris)
        origins = set(c.get("webOrigins") or [])
        origins.update(["${WEB_ORIGIN}", "https://*.variphi.com", "http://localhost:8080", "http://localhost:9090"])
        c["webOrigins"] = sorted(origins)
        break
else:
    sys.exit("thingsboard client not in realm-export.json")
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("realm-export.json updated")
PY
fi

# --- 4) Restart Keycloak to reload client config from DB ---
echo "==> Restarting Keycloak"
if [[ -f "${MS_DIR}/docker-compose.yml" ]]; then
  (cd "${MS_DIR}" && docker compose restart keycloak) || docker restart "${KC_CONTAINER}"
else
  docker restart "${KC_CONTAINER}"
fi

echo "==> Waiting for Keycloak..."
sleep 15
for i in 1 2 3 4 5 6; do
  if curl -sf "http://127.0.0.1:8080/auth/realms/${REALM}/.well-known/openid-configuration" >/dev/null 2>&1 || \
     curl -sf "http://127.0.0.1:8080/realms/${REALM}/.well-known/openid-configuration" >/dev/null 2>&1; then
    echo "Keycloak is up"
    break
  fi
  sleep 5
done

echo "==> Verify redirect_uri (from gateway)"
curl -sS -o /tmp/kc-verify.html -w "HTTP %{http_code}\n" \
  "https://api.edge.variphi.com/auth/realms/${REALM}/protocol/openid-connect/auth?client_id=${CLIENT}&redirect_uri=$(python3 -c 'import urllib.parse; print(urllib.parse.quote(\"${REDIRECT_EXACT}\"))')&response_type=code&scope=openid" || true
if grep -q "Invalid parameter: redirect_uri" /tmp/kc-verify.html 2>/dev/null; then
  echo "FAIL: redirect_uri still rejected" >&2
  exit 1
fi
echo "OK: auth endpoint accepts viot redirect_uri"
