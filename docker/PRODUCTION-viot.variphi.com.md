# Variphi IoT — Production Deployment (viot.variphi.com)

This guide deploys the Variphi IoT fork (ThingsBoard + Keycloak SSO) to production at
**https://viot.variphi.com**, fronted by a TLS reverse proxy, using external PostgreSQL,
Redis, and Keycloak.

```
Browser ──HTTPS──▶  Reverse proxy (nginx/traefik)  ──HTTP──▶  mytb (tb-node :8080)
                    TLS for viot.variphi.com                   │
                                                               ├─▶ PostgreSQL  (tb database)
                    auth.variphi.com (Keycloak) ◀──────────────┤─▶ Redis        (cache)
                                                               └─▶ Keycloak     (OIDC: token/jwks/userinfo)
```

---
## 0. Prerequisites
- A host with Docker + Docker Compose, and DNS:
  - `viot.variphi.com` → the app/reverse-proxy host
  - `auth.variphi.com` → Keycloak (can be the same host/proxy)
- TLS certificates for both names (Let's Encrypt via the proxy).
- External **PostgreSQL** reachable from the app host, with an **empty** database `tb` owned by a user.
- External **Redis** reachable from the app host (with password).
- **Keycloak** running with the `things` realm.

---
## 1. Keycloak — the `thingsboard` client (production)
In the `things` realm, ensure a **confidential** client `thingsboard`:
- Client authentication: **On**; **Standard flow** enabled.
- **Valid redirect URIs:** `https://viot.variphi.com/login/oauth2/code/*`
- **Valid post logout redirect URIs:** `https://viot.variphi.com/*`
- **Web origins:** `https://viot.variphi.com`
- Copy the **client secret** (used as `TB_OAUTH2_CLIENT_SECRET`).
- Map `email`, `given_name`, `family_name` (default `profile`+`email` scopes already do this).

Keycloak itself must be served at a stable public issuer **`https://auth.variphi.com/realms/things`**
reachable by BOTH the browser and the tb-node container (so no split-issuer is needed in prod):
set `KC_HOSTNAME=https://auth.variphi.com` and run Keycloak behind TLS.

> The realm seed lives at `vgi-microservices/keycloak/realm-export.json` (client `thingsboard`,
> secret + redirect/post-logout URIs). For prod, set the real secret and the `viot.variphi.com` URIs.

---
## 2. Build & publish the Variphi IoT image
On a build host (JDK 25 + Maven + Docker):
```bash
cd thingsboard
JAVA_HOME=<jdk25> MAVEN_OPTS=-Xmx2560m NODE_OPTIONS=--max_old_space_size=4096 \
mvn -T2 clean install -DskipTests \
  -Dlicense.skip=true -Dcheckstyle.skip=true \
  -Dpkg.skip=false -Ddockerfile.skip=false -pl msa/tb-node -am

docker tag thingsboard/tb-node:latest registry.example.com/variphi/tb-node:1.0.0
docker push registry.example.com/variphi/tb-node:1.0.0
# No registry? ship it:  docker save registry.example.com/variphi/tb-node:1.0.0 | ssh prod 'docker load'
```

---
## 3. Production env file
On the prod host, in `thingsboard/docker/`, copy the template and fill real values:
```bash
cp variphi-prod.env.example variphi-prod.env   # then edit (keep OUT of git)
```
`variphi-prod.env` (key values for viot.variphi.com):
```
TB_IMAGE=registry.example.com/variphi/tb-node:1.0.0

DATABASE_HOST=<pg-host>
DATABASE_PORT=5432
DATABASE_NAME=tb
DATABASE_USER=variphi
DATABASE_PASSWORD=<strong>

CACHE_TYPE=redis
REDIS_HOST=<redis-host>
REDIS_PORT=6379
REDIS_PASSWORD=<strong>

TB_OAUTH2_CLIENT_SECRET=<keycloak thingsboard client secret>
SECURITY_OAUTH2_KEYCLOAK_ISSUER_URI=https://auth.variphi.com/realms/things
SECURITY_OAUTH2_KEYCLOAK_AUTH_ISSUER_URI=          # leave EMPTY in prod (single public issuer)
SECURITY_OAUTH2_KEYCLOAK_DOMAIN_NAME=viot.variphi.com

DEVICE_CONNECTIVITY_HTTP_HOST=viot.variphi.com
DEVICE_CONNECTIVITY_HTTP_PORT=443
DEVICE_CONNECTIVITY_MQTT_HOST=viot.variphi.com
DEVICE_CONNECTIVITY_MQTT_PORT=8883

LOAD_DEMO=false
```

---
## 4. First-run install (once, on the EMPTY `tb` database)
Seeds the schema, system data, and the Keycloak OAuth2 client/domain (`viot.variphi.com`):
```bash
cd thingsboard/docker
docker compose --env-file variphi-prod.env -f docker-compose.variphi-sso.yml \
  --profile install up tb-install    # runs install, then exits
```
> Run ONLY once on a fresh DB. Re-running on a populated DB errors. For version upgrades use the
> tb-node `UPGRADE_TB=true` flow instead.

---
## 5. Start Variphi IoT
```bash
docker compose --env-file variphi-prod.env -f docker-compose.variphi-sso.yml up -d mytb
```
The container exposes **8080** (HTTP/UI) and **1883** (MQTT). Do NOT publish them publicly;
let the reverse proxy reach them on the internal network (or bind to 127.0.0.1).

---
## 6. Reverse proxy (TLS termination) — nginx example
```nginx
server {
  listen 443 ssl http2;
  server_name viot.variphi.com;
  ssl_certificate     /etc/letsencrypt/live/viot.variphi.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/viot.variphi.com/privkey.pem;

  client_max_body_size 50m;

  location / {
    proxy_pass http://127.0.0.1:8080;     # mytb container HTTP
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;   # IMPORTANT: TB builds the OAuth2 redirect from this
    proxy_set_header X-Forwarded-Port  443;
    # WebSocket (telemetry/notifications):
    proxy_set_header Upgrade    $http_upgrade;
    proxy_set_header Connection "upgrade";
  }
}
# MQTT over TLS (8883) -> mytb 1883 needs a stream{} block or a TLS-terminating MQTT proxy.
```
`X-Forwarded-Proto: https` is required so ThingsBoard generates `https://viot.variphi.com/login/oauth2/code/`
as the OAuth2 redirect (matching the Keycloak client) — otherwise SSO fails.

---
## 7. Post-deploy settings (in the UI, as sysadmin)
- **System Settings → General → Base URL** = `https://viot.variphi.com` (used for share/email links).
- Verify **Security → OAuth2** shows the seeded `Variphi SSO` (Keycloak) client on domain `viot.variphi.com`.

---
## 8. Verify
1. `https://viot.variphi.com` → auto-redirects to `https://auth.variphi.com/realms/things/...` (Keycloak).
2. Log in → lands authenticated on the home page.
3. **Logout** → ends the Keycloak session (RP-initiated) → back to the Keycloak login (no silent re-login, no `authorization_request_not_found`).
4. Add a device → "Check connectivity" shows `https://viot.variphi.com` (HTTP) / `viot.variphi.com:8883` (MQTTS).
5. Sysadmin emergency local login (not in Keycloak): `https://viot.variphi.com/login?localLogin=true`.

---
## Updating to a new version
Build a new tag, push, then:
```bash
# bump TB_IMAGE in variphi-prod.env, then:
docker compose --env-file variphi-prod.env -f docker-compose.variphi-sso.yml \
  --profile install run --rm -e UPGRADE_TB=true mytb   # DB schema upgrade (if any)
docker compose --env-file variphi-prod.env -f docker-compose.variphi-sso.yml up -d mytb
```
