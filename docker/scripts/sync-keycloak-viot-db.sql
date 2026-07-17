-- Keycloak DB fixes for realm "viot" + client "viot" (Virtuoso ThingsBoard SSO).
-- Run: psql -h <KEYCLOAK_DB_HOST> -U variphi -d keycloak -f sync-keycloak-viot-db.sql

\set realm_name 'viot'
\set client_id 'viot'

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

INSERT INTO client_attributes (client_id, name, value)
SELECT c.id, 'post.logout.redirect.uris',
       'https://viot.virtuosonetsoft.com/*##https://viot.virtuosonetsoft.com/oauth2/authorization/*'
FROM client c
JOIN realm r ON c.realm_id = r.id
WHERE r.name = :'realm_name' AND c.client_id = :'client_id'
ON CONFLICT (client_id, name) DO UPDATE SET value = EXCLUDED.value;

UPDATE realm SET login_theme = 'variphi', display_name = 'Virtuoso IoT'
WHERE name = :'realm_name';

UPDATE realm SET not_before = extract(epoch from now())::int WHERE name = :'realm_name';
