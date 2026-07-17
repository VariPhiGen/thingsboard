#!/usr/bin/env bash
# Configure gateway Keycloak (api.edge.variphi.com) realm viot for Variphi TB only.
# VGI microservices continue using realm "things" on the same Keycloak instance.
set -euo pipefail

VIOT_BASE="https://viot.variphi.com"
REDIRECT_EXACT="${VIOT_BASE}/login/oauth2/code/"
REDIRECT_WILD="${VIOT_BASE}/login/oauth2/code/*"
POST_LOGOUT_URIS="${VIOT_BASE}/*##${VIOT_BASE}/oauth2/authorization/*"
CLIENT_SECRET="${VARIPHI_CLIENT_SECRET:-07efad71-2d29-4df2-bfe7-6fa998ddff68}"

REALM="viot"
CLIENT="viot"
SOURCE_REALM="things"
KC_CONTAINER="${KC_CONTAINER:-keycloak}"

MS_DIR="${VG_MICROSERVICES_DIR:-/var/vgi-microservices}"
if [[ ! -d "${MS_DIR}" ]]; then
  for d in /var/vgi-microservices /home/ubuntu/vgi-microservices /opt/vgi-microservices; do
    if [[ -d "$d" ]]; then MS_DIR="$d"; break; fi
  done
fi

if ! docker ps --format '{{.Names}}' | grep -qx "${KC_CONTAINER}"; then
  echo "ERROR: container ${KC_CONTAINER} not running" >&2
  docker ps --format '{{.Names}}'
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

  if ! /opt/keycloak/bin/kcadm.sh get realms/${REALM} >/dev/null 2>&1; then
    echo \"==> Creating realm ${REALM}\"
    /opt/keycloak/bin/kcadm.sh create realms \
      -s realm=${REALM} \
      -s enabled=true \
      -s displayName='Variphi IoT' \
      -s loginTheme=variphi \
      -s sslRequired=none \
      -s registrationAllowed=false \
      -s loginWithEmailAllowed=true \
      -s duplicateEmailsAllowed=false \
      -s resetPasswordAllowed=true \
      -s rememberMe=true
  else
    echo \"==> Updating realm ${REALM}\"
    /opt/keycloak/bin/kcadm.sh update realms/${REALM} \
      -s enabled=true \
      -s displayName='Variphi IoT' \
      -s loginTheme=variphi
  fi

  CID=\$(/opt/keycloak/bin/kcadm.sh get clients -r ${REALM} -q clientId=${CLIENT} --fields id --format csv --noquotes 2>/dev/null | tail -1 || true)
  if [[ -z \"\${CID}\" || \"\${CID}\" == \"id\" ]]; then
    echo \"==> Creating client ${CLIENT}\"
    /opt/keycloak/bin/kcadm.sh create clients -r ${REALM} \
      -s clientId=${CLIENT} \
      -s name='VIOT' \
      -s description='Variphi IoT ThingsBoard SSO' \
      -s enabled=true \
      -s publicClient=false \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=true \
      -s serviceAccountsEnabled=false \
      -s clientAuthenticatorType=client-secret \
      -s secret='${CLIENT_SECRET}' \
      -s 'redirectUris=[\"${REDIRECT_EXACT}\",\"${REDIRECT_WILD}\",\"http://localhost:8080/login/oauth2/code/*\",\"http://localhost:9090/login/oauth2/code/*\"]' \
      -s 'webOrigins=[\"${VIOT_BASE}\",\"https://*.variphi.com\",\"http://localhost:8080\",\"http://localhost:9090\"]' \
      -s 'attributes.\"post.logout.redirect.uris\"=\"${POST_LOGOUT_URIS}\"' \
      -s baseUrl='${VIOT_BASE}'
    CID=\$(/opt/keycloak/bin/kcadm.sh get clients -r ${REALM} -q clientId=${CLIENT} --fields id --format csv --noquotes | tail -1)
  else
    echo \"==> Updating client ${CLIENT} (\${CID}) — Variphi URIs only\"
    /opt/keycloak/bin/kcadm.sh update \"clients/\${CID}\" -r ${REALM} \
      -s enabled=true \
      -s name='VIOT' \
      -s standardFlowEnabled=true \
      -s secret='${CLIENT_SECRET}' \
      -s 'redirectUris=[\"${REDIRECT_EXACT}\",\"${REDIRECT_WILD}\",\"http://localhost:8080/login/oauth2/code/*\",\"http://localhost:9090/login/oauth2/code/*\"]' \
      -s 'webOrigins=[\"${VIOT_BASE}\",\"https://*.variphi.com\",\"http://localhost:8080\",\"http://localhost:9090\"]' \
      -s 'attributes.\"post.logout.redirect.uris\"=\"${POST_LOGOUT_URIS}\"' \
      -s baseUrl='${VIOT_BASE}'
  fi

  add_mapper() {
    local name=\"\$1\" attr=\"\$2\" claim=\"\$3\"
    if /opt/keycloak/bin/kcadm.sh get \"clients/\${CID}/protocol-mappers/models\" -r ${REALM} 2>/dev/null | grep -q \"\\\"\${name}\\\"\"; then
      return 0
    fi
    /opt/keycloak/bin/kcadm.sh create \"clients/\${CID}/protocol-mappers/models\" -r ${REALM} \
      -s name=\"\${name}\" \
      -s protocol=openid-connect \
      -s protocolMapper=oidc-usermodel-attribute-mapper \
      -s 'config.\"user.attribute\"'=\"\${attr}\" \
      -s 'config.\"claim.name\"'=\"\${claim}\" \
      -s 'config.\"jsonType.label\"'=String \
      -s 'config.\"id.token.claim\"'=true \
      -s 'config.\"access.token.claim\"'=true \
      -s 'config.\"userinfo.token.claim\"'=true \
      -s 'config.\"introspection.token.claim\"'=true
  }

  add_mapper variphi-user_type user_type user_type
  add_mapper variphi-client_id client_id client_id
  echo \"Client ${CLIENT} ready (Variphi only)\"
"

echo "==> Importing human users from ${SOURCE_REALM} -> ${REALM}"
docker exec "${KC_CONTAINER}" bash -c "
  /opt/keycloak/bin/kc.sh export --dir /tmp/kc-variphi-export --realm ${SOURCE_REALM} --users realm_file >/dev/null 2>&1 || true
"
docker cp "${KC_CONTAINER}:/tmp/kc-variphi-export/${SOURCE_REALM}-realm.json" /tmp/things-realm-variphi.json 2>/dev/null || true

if [[ -f /tmp/things-realm-variphi.json ]]; then
  python3 << 'PY'
import json
from pathlib import Path
src = Path("/tmp/things-realm-variphi.json")
out = Path("/tmp/variphi-viot-users-import.json")
data = json.loads(src.read_text())
users = []
for u in data.get("users", []):
    if u.get("username", "").startswith("service-account-"):
        continue
    users.append({
        "username": u.get("username"),
        "enabled": u.get("enabled", True),
        "email": u.get("email"),
        "emailVerified": u.get("emailVerified", False),
        "firstName": u.get("firstName"),
        "lastName": u.get("lastName"),
        "attributes": u.get("attributes"),
        "credentials": u.get("credentials", []),
        "requiredActions": u.get("requiredActions", []),
    })
out.write_text(json.dumps({"users": users}, indent=2))
print(f"Prepared {len(users)} user(s)")
PY
  docker cp /tmp/variphi-viot-users-import.json "${KC_CONTAINER}:/tmp/variphi-viot-users-import.json"
  docker exec "${KC_CONTAINER}" bash -c "
    /opt/keycloak/bin/kcadm.sh config credentials --server http://127.0.0.1:8080/auth --realm master \
      --user \"\${KEYCLOAK_ADMIN:-admin}\" --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\" 2>/dev/null
    /opt/keycloak/bin/kcadm.sh create partialImport -r ${REALM} -s ifResourceExists=SKIP \
      -o -f /tmp/variphi-viot-users-import.json >/dev/null 2>&1 || \
    /opt/keycloak/bin/kcadm.sh create partialImport -r ${REALM} -s ifResourceExists=OVERWRITE \
      -o -f /tmp/variphi-viot-users-import.json >/dev/null 2>&1 || true
  "
fi

docker restart "${KC_CONTAINER}"
sleep 15
echo "OK: Gateway Keycloak realm ${REALM} configured for Variphi (viot.variphi.com)"
echo "VARIPHI_CLIENT_SECRET=${CLIENT_SECRET}"
