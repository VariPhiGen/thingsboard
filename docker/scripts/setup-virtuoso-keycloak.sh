#!/usr/bin/env bash
# Deploy dedicated Virtuoso Keycloak on gateway + nginx + realm viot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GATEWAY_HOST="${GATEWAY_HOST:-43.204.247.12}"
GATEWAY_USER="${GATEWAY_USER:-ubuntu}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/keycloak-virtuoso}"
THEME_SRC="${SCRIPT_DIR}/../keycloak-theme/virtuoso"

VIOT_BASE="https://viot.virtuosonetsoft.com"
REDIRECT_EXACT="${VIOT_BASE}/login/oauth2/code/"
REDIRECT_WILD="${VIOT_BASE}/login/oauth2/code/*"
POST_LOGOUT_URIS="${VIOT_BASE}/*##${VIOT_BASE}/oauth2/authorization/*"
CLIENT_SECRET="${VIRTUOSO_CLIENT_SECRET:-cfab5cc2-8039-4547-a5cf-df757d01a247}"
REALM="viot"
CLIENT="viot"
KC_CONTAINER="keycloak-virtuoso"

SSH_KEY="${SSH_KEY:-}"
for candidate in "${HOME}/.ssh/microserive-prod.pem" "${HOME}/microserive-prod.pem"; do
  [[ -z "${SSH_KEY}" && -f "${candidate}" ]] && SSH_KEY="${candidate}"
done
[[ -f "${SSH_KEY}" ]] || { echo "ERROR: SSH key not found" >&2; exit 1; }
SSH_OPTS=(-i "${SSH_KEY}" -o StrictHostKeyChecking=no -o ConnectTimeout=15)

echo "==> Creating Postgres database keycloak_virtuoso (if missing)"
PGPASSWORD="${KC_DB_PASSWORD:-vgi@2026}" psql -h "${KC_DB_HOST:-3.110.77.148}" -U "${KC_DB_USER:-variphi}" -d postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname = 'keycloak_virtuoso'" | grep -q 1 || \
PGPASSWORD="${KC_DB_PASSWORD:-vgi@2026}" psql -h "${KC_DB_HOST:-3.110.77.148}" -U "${KC_DB_USER:-variphi}" -d postgres -c \
  "CREATE DATABASE keycloak_virtuoso OWNER variphi;"

echo "==> Syncing keycloak-virtuoso compose + theme to gateway"
ssh "${SSH_OPTS[@]}" "${GATEWAY_USER}@${GATEWAY_HOST}" "mkdir -p '${REMOTE_DIR}/themes'"
rsync -avz -e "ssh ${SSH_OPTS[*]}" \
  "${SCRIPT_DIR}/../keycloak-virtuoso/docker-compose.yml" \
  "${GATEWAY_USER}@${GATEWAY_HOST}:${REMOTE_DIR}/"
rsync -avz -e "ssh ${SSH_OPTS[*]}" \
  "${THEME_SRC}/" "${GATEWAY_USER}@${GATEWAY_HOST}:${REMOTE_DIR}/themes/virtuoso/"

echo "==> Starting keycloak-virtuoso container"
ssh "${SSH_OPTS[@]}" "${GATEWAY_USER}@${GATEWAY_HOST}" bash -s <<REMOTE
set -euo pipefail
cd '${REMOTE_DIR}'
docker compose up -d
for i in \$(seq 1 30); do
  if curl -sf http://127.0.0.1:8082/realms/master >/dev/null 2>&1; then
    echo "Keycloak Virtuoso is up"
    break
  fi
  sleep 3
done
REMOTE

echo "==> Configuring realm viot + client viot on keycloak-virtuoso"
scp "${SSH_OPTS[@]}" "${SCRIPT_DIR}/fix-virtuoso-keycloak-viot.sh" \
  "${GATEWAY_USER}@${GATEWAY_HOST}:/tmp/fix-virtuoso-keycloak-viot.sh"
ssh "${SSH_OPTS[@]}" "${GATEWAY_USER}@${GATEWAY_HOST}" \
  "chmod +x /tmp/fix-virtuoso-keycloak-viot.sh && /tmp/fix-virtuoso-keycloak-viot.sh"

echo "==> Installing nginx vhost for auth.virtuosonetsoft.variphi.com"
ssh "${SSH_OPTS[@]}" "${GATEWAY_USER}@${GATEWAY_HOST}" bash -s <<'NGINX'
set -euo pipefail
SITE=/etc/nginx/sites-available/auth.virtuosonetsoft.variphi.com
CERT_DIR=/etc/letsencrypt/live/auth.virtuosonetsoft.variphi.com
SELF_DIR=/etc/nginx/ssl/auth.virtuosonetsoft.variphi.com

if [[ ! -f "${CERT_DIR}/fullchain.pem" ]]; then
  sudo certbot certonly --nginx -d auth.virtuosonetsoft.variphi.com --non-interactive --agree-tos -m admin@variphi.com 2>/dev/null || \
  sudo certbot certonly --standalone -d auth.virtuosonetsoft.variphi.com --non-interactive --agree-tos -m admin@variphi.com \
    --pre-hook "sudo systemctl stop nginx" --post-hook "sudo systemctl start nginx" 2>/dev/null || true
fi

if [[ ! -f "${CERT_DIR}/fullchain.pem" ]]; then
  echo "WARN: Let's Encrypt cert unavailable (DNS may be missing); using self-signed cert"
  sudo mkdir -p "${SELF_DIR}"
  if [[ ! -f "${SELF_DIR}/fullchain.pem" ]]; then
    sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
      -keyout "${SELF_DIR}/privkey.pem" \
      -out "${SELF_DIR}/fullchain.pem" \
      -subj "/CN=auth.virtuosonetsoft.variphi.com"
  fi
  CERT_DIR="${SELF_DIR}"
fi

sudo tee "$SITE" >/dev/null <<EOF
server {
    listen 80;
    server_name auth.virtuosonetsoft.variphi.com;
    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name auth.virtuosonetsoft.variphi.com;

    ssl_certificate ${CERT_DIR}/fullchain.pem;
    ssl_certificate_key ${CERT_DIR}/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        proxy_pass http://127.0.0.1:8082;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;
    }
}
EOF

sudo ln -sf "$SITE" /etc/nginx/sites-enabled/auth.virtuosonetsoft.variphi.com
sudo nginx -t && sudo systemctl reload nginx
NGINX

echo "OK: Virtuoso Keycloak at https://auth.virtuosonetsoft.variphi.com"
echo "VIRTUOSO_CLIENT_SECRET=${CLIENT_SECRET}"
