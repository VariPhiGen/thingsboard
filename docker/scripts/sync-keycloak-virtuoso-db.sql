-- Configure Keycloak thingsboard client for Virtuoso NetSoft only (realm "things").
-- Run against Keycloak DB: psql -h <KEYCLOAK_DB_HOST> -U variphi -d keycloak -f sync-keycloak-virtuoso-db.sql

\set realm_name 'things'
\set client_id 'thingsboard'

-- Remove Variphi redirect URIs and web origins from the shared client.
DELETE FROM redirect_uris ru
USING client c
JOIN realm r ON c.realm_id = r.id
WHERE ru.client_id = c.id
  AND r.name = :'realm_name'
  AND c.client_id = :'client_id'
  AND (ru.value LIKE 'https://viot.variphi.com%' OR ru.value LIKE 'https://%.variphi.com%');

DELETE FROM web_origins wo
USING client c
JOIN realm r ON c.realm_id = r.id
WHERE wo.client_id = c.id
  AND r.name = :'realm_name'
  AND c.client_id = :'client_id'
  AND (wo.value LIKE 'https://viot.variphi.com%' OR wo.value LIKE 'https://%.variphi.com%');

-- Virtuoso login redirect URIs.
INSERT INTO redirect_uris (client_id, value)
SELECT c.id, v.uri
FROM client c
JOIN realm r ON c.realm_id = r.id
CROSS JOIN (VALUES
  ('https://viot.virtuosonetsoft.com/login/oauth2/code/'),
  ('https://viot.virtuosonetsoft.com/login/oauth2/code/*')
) AS v(uri)
WHERE r.name = :'realm_name' AND c.client_id = :'client_id'
ON CONFLICT DO NOTHING;

INSERT INTO web_origins (client_id, value)
SELECT c.id, v.origin
FROM client c
JOIN realm r ON c.realm_id = r.id
CROSS JOIN (VALUES
  ('https://viot.virtuosonetsoft.com'),
  ('https://*.virtuosonetsoft.com')
) AS v(origin)
WHERE r.name = :'realm_name' AND c.client_id = :'client_id'
ON CONFLICT DO NOTHING;

-- Post-logout redirect URIs (Keycloak client attribute).
INSERT INTO client_attributes (client_id, name, value)
SELECT c.id, 'post.logout.redirect.uris',
       'https://viot.virtuosonetsoft.com/*##https://viot.virtuosonetsoft.com/oauth2/authorization/*'
FROM client c
JOIN realm r ON c.realm_id = r.id
WHERE r.name = :'realm_name' AND c.client_id = :'client_id'
ON CONFLICT (client_id, name) DO UPDATE SET value = EXCLUDED.value;

UPDATE realm SET not_before = extract(epoch from now())::int WHERE name = 'things';
