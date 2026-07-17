#!/usr/bin/env bash
# Create Keycloak realm "viot" + OAuth client "viot" for Virtuoso ThingsBoard SSO.
# Leaves legacy realm "things" intact (api-gateway + client-service still use it).
set -euo pipefail

VIOT_BASE="https://viot.virtuosonetsoft.com"
REDIRECT_EXACT="${VIOT_BASE}/login/oauth2/code/"
REDIRECT_WILD="${VIOT_BASE}/login/oauth2/code/*"
POST_LOGOUT_URIS="${VIOT_BASE}/*##${VIOT_BASE}/oauth2/authorization/*"
# Reuse existing TB secret so Virtuoso env migration is issuer/client-id only.
CLIENT_SECRET="${VIOT_CLIENT_SECRET:-4fb22520-6f00-49e7-9cd0-026cb3dc50e5}"

REALM="viot"
CLIENT="viot"
SOURCE_REALM="things"

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

  if ! /opt/keycloak/bin/kcadm.sh get realms/${REALM} >/dev/null 2>&1; then
    echo \"==> Creating realm ${REALM}\"
    /opt/keycloak/bin/kcadm.sh create realms \
      -s realm=${REALM} \
      -s enabled=true \
      -s displayName='Virtuoso IoT' \
      -s loginTheme=variphi \
      -s sslRequired=none \
      -s registrationAllowed=false \
      -s loginWithEmailAllowed=true \
      -s duplicateEmailsAllowed=false \
      -s resetPasswordAllowed=true \
      -s rememberMe=true
  else
    echo \"==> Realm ${REALM} exists; updating theme/display name\"
    /opt/keycloak/bin/kcadm.sh update realms/${REALM} \
      -s enabled=true \
      -s displayName='Virtuoso IoT' \
      -s loginTheme=variphi
  fi

  CID=\$(/opt/keycloak/bin/kcadm.sh get clients -r ${REALM} -q clientId=${CLIENT} --fields id --format csv --noquotes 2>/dev/null | tail -1 || true)
  if [[ -z \"\${CID}\" || \"\${CID}\" == \"id\" ]]; then
    echo \"==> Creating client ${CLIENT}\"
    /opt/keycloak/bin/kcadm.sh create clients -r ${REALM} \
      -s clientId=${CLIENT} \
      -s name='VIOT' \
      -s description='Virtuoso IoT ThingsBoard SSO' \
      -s enabled=true \
      -s publicClient=false \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=true \
      -s serviceAccountsEnabled=false \
      -s clientAuthenticatorType=client-secret \
      -s secret='${CLIENT_SECRET}' \
      -s 'redirectUris=[\"${REDIRECT_EXACT}\",\"${REDIRECT_WILD}\",\"http://localhost:8080/login/oauth2/code/*\",\"http://localhost:9090/login/oauth2/code/*\",\"http://localhost:9091/login/oauth2/code/*\"]' \
      -s 'webOrigins=[\"${VIOT_BASE}\",\"https://*.virtuosonetsoft.com\",\"http://localhost:8080\",\"http://localhost:9090\",\"http://localhost:9091\"]' \
      -s 'attributes.\"post.logout.redirect.uris\"=\"${POST_LOGOUT_URIS}\"' \
      -s baseUrl='${VIOT_BASE}'
    CID=\$(/opt/keycloak/bin/kcadm.sh get clients -r ${REALM} -q clientId=${CLIENT} --fields id --format csv --noquotes | tail -1)
  else
    echo \"==> Updating client ${CLIENT} (\${CID})\"
    /opt/keycloak/bin/kcadm.sh update \"clients/\${CID}\" -r ${REALM} \
      -s enabled=true \
      -s name='VIOT' \
      -s standardFlowEnabled=true \
      -s secret='${CLIENT_SECRET}' \
      -s 'redirectUris=[\"${REDIRECT_EXACT}\",\"${REDIRECT_WILD}\",\"http://localhost:8080/login/oauth2/code/*\",\"http://localhost:9090/login/oauth2/code/*\",\"http://localhost:9091/login/oauth2/code/*\"]' \
      -s 'webOrigins=[\"${VIOT_BASE}\",\"https://*.virtuosonetsoft.com\",\"http://localhost:8080\",\"http://localhost:9090\",\"http://localhost:9091\"]' \
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

  echo \"==> Ensuring protocol mappers on client ${CLIENT}\"
  add_mapper variphi-user_type user_type user_type
  add_mapper variphi-client_id client_id client_id

  echo \"Client ${CLIENT} ready in realm ${REALM}\"
"

echo "==> Migrating human users from realm ${SOURCE_REALM} -> ${REALM}"
docker exec "${KC_CONTAINER}" bash -c "
  set -e
  if [[ ! -f /tmp/kc-realm-export/${SOURCE_REALM}-realm.json ]]; then
    /opt/keycloak/bin/kc.sh export --dir /tmp/kc-realm-export --realm ${SOURCE_REALM} --users realm_file >/dev/null 2>&1 || true
  fi
"

docker cp "${KC_CONTAINER}:/tmp/kc-realm-export/${SOURCE_REALM}-realm.json" /tmp/things-realm.json 2>/dev/null || true

if [[ -f /tmp/things-realm.json ]]; then
  python3 << 'PY'
import json
from pathlib import Path

src = Path("/tmp/things-realm.json")
out = Path("/tmp/viot-users-import.json")
data = json.loads(src.read_text())
users = []
for u in data.get("users", []):
    uname = u.get("username", "")
    if uname.startswith("service-account-"):
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
print(f"Prepared {len(users)} user(s) for partial import -> {out}")
PY

  docker cp /tmp/viot-users-import.json "${KC_CONTAINER}:/tmp/viot-users-import.json"
  docker exec "${KC_CONTAINER}" bash -c "
    set -e
    /opt/keycloak/bin/kcadm.sh config credentials \
      --server http://127.0.0.1:8080/auth \
      --realm master \
      --user \"\${KEYCLOAK_ADMIN:-admin}\" \
      --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\" 2>/dev/null
    /opt/keycloak/bin/kcadm.sh create partialImport -r ${REALM} \
      -s ifResourceExists=SKIP \
      -o -f /tmp/viot-users-import.json >/dev/null 2>&1 || \
    /opt/keycloak/bin/kcadm.sh create partialImport -r ${REALM} \
      -s ifResourceExists=OVERWRITE \
      -o -f /tmp/viot-users-import.json >/dev/null 2>&1 || true
    echo \"User partial import attempted\"
  "
else
  echo "WARN: could not export ${SOURCE_REALM} users; create users manually in realm ${REALM}"
fi

if [[ -f "${MS_DIR}/docker-compose.yml" ]]; then
  (cd "${MS_DIR}" && docker compose restart keycloak) || docker restart "${KC_CONTAINER}"
else
  docker restart "${KC_CONTAINER}"
fi

sleep 15
echo "OK: Keycloak realm ${REALM} + client ${CLIENT} configured for Virtuoso IoT"
