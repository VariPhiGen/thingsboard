-- Idempotent Keycloak DB fixes for ThingsBoard SSO (realm "things", client "thingsboard").
-- Run: psql -h <KEYCLOAK_DB_HOST> -U variphi -d keycloak -f sync-keycloak-thingsboard-db.sql

\set client_id 'thingsboard'
\set realm_name 'things'

INSERT INTO redirect_uris (client_id, value)
SELECT c.id, v.uri
FROM client c
JOIN realm r ON c.realm_id = r.id
CROSS JOIN (VALUES
  ('https://viot.variphi.com/login/oauth2/code/'),
  ('https://viot.variphi.com/login/oauth2/code/*'),
  ('https://viot.variphi.com/*'),
  ('http://localhost:8080/login/oauth2/code/*'),
  ('http://localhost:9090/login/oauth2/code/*'),
  ('https://viot.virtuosonetsoft.com/login/oauth2/code/'),
  ('https://viot.virtuosonetsoft.com/login/oauth2/code/*'),
  ('https://viot.virtuosonetsoft.com/*')
) AS v(uri)
WHERE r.name = :'realm_name' AND c.client_id = :'client_id'
ON CONFLICT DO NOTHING;

-- Keycloak redirect_uris has no unique constraint on (client_id,value) in all versions;
-- use NOT EXISTS for safety:
INSERT INTO redirect_uris (client_id, value)
SELECT c.id, 'https://viot.variphi.com/login/oauth2/code/'
FROM client c JOIN realm r ON c.realm_id = r.id
WHERE r.name = 'things' AND c.client_id = 'thingsboard'
  AND NOT EXISTS (SELECT 1 FROM redirect_uris ru WHERE ru.client_id = c.id AND ru.value = 'https://viot.variphi.com/login/oauth2/code/');

INSERT INTO redirect_uris (client_id, value)
SELECT c.id, 'https://viot.variphi.com/login/oauth2/code/*'
FROM client c JOIN realm r ON c.realm_id = r.id
WHERE r.name = 'things' AND c.client_id = 'thingsboard'
  AND NOT EXISTS (SELECT 1 FROM redirect_uris ru WHERE ru.client_id = c.id AND ru.value = 'https://viot.variphi.com/login/oauth2/code/*');

INSERT INTO redirect_uris (client_id, value)
SELECT c.id, 'https://viot.virtuosonetsoft.com/login/oauth2/code/'
FROM client c JOIN realm r ON c.realm_id = r.id
WHERE r.name = 'things' AND c.client_id = 'thingsboard'
  AND NOT EXISTS (SELECT 1 FROM redirect_uris ru WHERE ru.client_id = c.id AND ru.value = 'https://viot.virtuosonetsoft.com/login/oauth2/code/');

INSERT INTO redirect_uris (client_id, value)
SELECT c.id, 'https://viot.virtuosonetsoft.com/login/oauth2/code/*'
FROM client c JOIN realm r ON c.realm_id = r.id
WHERE r.name = 'things' AND c.client_id = 'thingsboard'
  AND NOT EXISTS (SELECT 1 FROM redirect_uris ru WHERE ru.client_id = c.id AND ru.value = 'https://viot.virtuosonetsoft.com/login/oauth2/code/*');

INSERT INTO web_origins (client_id, value)
SELECT c.id, 'https://viot.variphi.com'
FROM client c JOIN realm r ON c.realm_id = r.id
WHERE r.name = 'things' AND c.client_id = 'thingsboard'
  AND NOT EXISTS (SELECT 1 FROM web_origins wo WHERE wo.client_id = c.id AND wo.value = 'https://viot.variphi.com');

INSERT INTO web_origins (client_id, value)
SELECT c.id, 'https://viot.virtuosonetsoft.com'
FROM client c JOIN realm r ON c.realm_id = r.id
WHERE r.name = 'things' AND c.client_id = 'thingsboard'
  AND NOT EXISTS (SELECT 1 FROM web_origins wo WHERE wo.client_id = c.id AND wo.value = 'https://viot.virtuosonetsoft.com');

UPDATE client SET
  enabled = true,
  standard_flow_enabled = true,
  base_url = 'https://viot.variphi.com',
  root_url = 'https://viot.variphi.com',
  not_before = extract(epoch from now())::int
WHERE client_id = 'thingsboard'
  AND realm_id = (SELECT id FROM realm WHERE name = 'things');

UPDATE realm SET not_before = extract(epoch from now())::int WHERE name = 'things';
