#!/usr/bin/env bash
# Configure keycloak-virtuoso (auth.virtuosonetsoft.variphi.com) realm viot for Virtuoso TB only.
set -euo pipefail

VIOT_BASE="https://viot.virtuosonetsoft.com"
REDIRECT_EXACT="${VIOT_BASE}/login/oauth2/code/"
REDIRECT_WILD="${VIOT_BASE}/login/oauth2/code/*"
POST_LOGOUT_URIS="${VIOT_BASE}/*##${VIOT_BASE}/oauth2/authorization/*"
CLIENT_SECRET="${VIRTUOSO_CLIENT_SECRET:-cfab5cc2-8039-4547-a5cf-df757d01a247}"

REALM="viot"
CLIENT="viot"
SOURCE_REALM="viot"
SOURCE_KC_CONTAINER="${SOURCE_KC_CONTAINER:-keycloak}"
KC_CONTAINER="${KC_CONTAINER:-keycloak-virtuoso}"

if ! docker ps --format '{{.Names}}' | grep -qx "${KC_CONTAINER}"; then
  echo "ERROR: container ${KC_CONTAINER} not running" >&2
  docker ps --format '{{.Names}}'
  exit 1
fi
echo "Keycloak container: ${KC_CONTAINER}"

docker exec "${KC_CONTAINER}" bash -c "
  set -e
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://127.0.0.1:8080 \
    --realm master \
    --user \"\${KEYCLOAK_ADMIN:-admin}\" \
    --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\" 2>/dev/null || \
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://127.0.0.1:8080/auth \
    --realm master \
    --user \"\${KEYCLOAK_ADMIN:-admin}\" \
    --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\"

  if ! /opt/keycloak/bin/kcadm.sh get realms/${REALM} >/dev/null 2>&1; then
    echo \"==> Creating realm ${REALM}\"
    /opt/keycloak/bin/kcadm.sh create realms \
      -s realm=${REALM} \
      -s enabled=true \
      -s displayName='Virtuoso IoT' \
      -s loginTheme=virtuoso \
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
      -s displayName='Virtuoso IoT' \
      -s loginTheme=virtuoso
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
      -s 'redirectUris=[\"${REDIRECT_EXACT}\",\"${REDIRECT_WILD}\",\"http://localhost:9091/login/oauth2/code/*\"]' \
      -s 'webOrigins=[\"${VIOT_BASE}\",\"https://*.virtuosonetsoft.com\",\"http://localhost:9091\"]' \
      -s 'attributes.\"post.logout.redirect.uris\"=\"${POST_LOGOUT_URIS}\"' \
      -s baseUrl='${VIOT_BASE}'
    CID=\$(/opt/keycloak/bin/kcadm.sh get clients -r ${REALM} -q clientId=${CLIENT} --fields id --format csv --noquotes | tail -1)
  else
    echo \"==> Updating client ${CLIENT} (\${CID}) — Virtuoso URIs only\"
    /opt/keycloak/bin/kcadm.sh update \"clients/\${CID}\" -r ${REALM} \
      -s enabled=true \
      -s name='VIOT' \
      -s standardFlowEnabled=true \
      -s secret='${CLIENT_SECRET}' \
      -s 'redirectUris=[\"${REDIRECT_EXACT}\",\"${REDIRECT_WILD}\",\"http://localhost:9091/login/oauth2/code/*\"]' \
      -s 'webOrigins=[\"${VIOT_BASE}\",\"https://*.virtuosonetsoft.com\",\"http://localhost:9091\"]' \
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
  echo \"Client ${CLIENT} ready (Virtuoso only)\"

  echo \"==> Ensuring client-service federation on realm ${REALM}\"
  if /opt/keycloak/bin/kcadm.sh get components -r ${REALM} -q name=client-service 2>/dev/null | grep -q client-service-federation; then
    echo \"Federation client-service already configured\"
  else
    /opt/keycloak/bin/kcadm.sh create components -r ${REALM} \
      -s name=client-service \
      -s providerId=client-service-federation \
      -s providerType=org.keycloak.storage.UserStorageProvider \
      -s 'config.baseUrl=[\"http://client-service:4801\"]' \
      -s 'config.sharedSecret=[\"vgi-federation-secret-2026\"]' \
      -s 'config.cachePolicy=[\"NO_CACHE\"]' \
      -s 'config.priority=[\"0\"]' \
      -s 'config.enabled=[\"true\"]'
    echo \"Federation client-service created\"
  fi
"

echo "==> Importing human users from ${SOURCE_KC_CONTAINER}:${SOURCE_REALM} -> ${KC_CONTAINER}:${REALM}"
if docker ps --format '{{.Names}}' | grep -qx "${SOURCE_KC_CONTAINER}"; then
  docker exec "${SOURCE_KC_CONTAINER}" bash -c "
    /opt/keycloak/bin/kc.sh export --dir /tmp/kc-virtuoso-export --realm ${SOURCE_REALM} --users realm_file >/dev/null 2>&1 || true
  "
  docker cp "${SOURCE_KC_CONTAINER}:/tmp/kc-virtuoso-export/${SOURCE_REALM}-realm.json" /tmp/virtuoso-source-realm.json 2>/dev/null || true
fi

if [[ -f /tmp/virtuoso-source-realm.json ]]; then
  python3 << 'PY'
import json
from pathlib import Path
src = Path("/tmp/virtuoso-source-realm.json")
out = Path("/tmp/virtuoso-viot-users-import.json")
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
  docker cp /tmp/virtuoso-viot-users-import.json "${KC_CONTAINER}:/tmp/virtuoso-viot-users-import.json"
  docker exec "${KC_CONTAINER}" bash -c "
    /opt/keycloak/bin/kcadm.sh config credentials --server http://127.0.0.1:8080 --realm master \
      --user \"\${KEYCLOAK_ADMIN:-admin}\" --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\" 2>/dev/null || \
    /opt/keycloak/bin/kcadm.sh config credentials --server http://127.0.0.1:8080/auth --realm master \
      --user \"\${KEYCLOAK_ADMIN:-admin}\" --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\"
    /opt/keycloak/bin/kcadm.sh create partialImport -r ${REALM} -s ifResourceExists=SKIP \
      -o -f /tmp/virtuoso-viot-users-import.json >/dev/null 2>&1 || \
    /opt/keycloak/bin/kcadm.sh create partialImport -r ${REALM} -s ifResourceExists=OVERWRITE \
      -o -f /tmp/virtuoso-viot-users-import.json >/dev/null 2>&1 || true
  "
else
  docker exec "${KC_CONTAINER}" bash -c "
    set -e
    /opt/keycloak/bin/kcadm.sh config credentials --server http://127.0.0.1:8080 --realm master \
      --user \"\${KEYCLOAK_ADMIN:-admin}\" --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\" 2>/dev/null || \
    /opt/keycloak/bin/kcadm.sh config credentials --server http://127.0.0.1:8080/auth --realm master \
      --user \"\${KEYCLOAK_ADMIN:-admin}\" --password \"\${KEYCLOAK_ADMIN_PASSWORD:-admin}\"
    if ! /opt/keycloak/bin/kcadm.sh get users -r ${REALM} -q username=demo --fields id 2>/dev/null | grep -q id; then
      /opt/keycloak/bin/kcadm.sh create users -r ${REALM} -s username=demo -s enabled=true \
        -s email=demo@things.local -s emailVerified=true -s firstName=Demo -s lastName=User
      /opt/keycloak/bin/kcadm.sh set-password -r ${REALM} --username demo --new-password demo --temporary=false
    fi
  "
fi

docker restart "${KC_CONTAINER}"
sleep 15
echo "OK: Virtuoso Keycloak realm ${REALM} configured (viot.virtuosonetsoft.com)"
echo "VIRTUOSO_CLIENT_SECRET=${CLIENT_SECRET}"
