-- Post-clone migration: re-point copied TB database to viot.virtuosonetsoft.com
-- Run: PGPASSWORD=... psql -h 13.206.196.162 -U variphi -d tb_virtuoso -f migrate-cloned-tb-domain.sql

-- Base URL (admin_settings → general)
UPDATE admin_settings
SET json_value = jsonb_set(json_value::jsonb, '{baseUrl}', '"https://viot.virtuosonetsoft.com"')
WHERE key = 'general';

-- OAuth2 domain binding
UPDATE domain SET name = 'viot.virtuosonetsoft.com'
WHERE name = 'viot.variphi.com';

-- SSO client display name (must match SECURITY_OAUTH2_KEYCLOAK_TITLE in env)
UPDATE oauth2_client
SET title = 'Virtuoso NetSoft SSO', login_button_label = 'Virtuoso NetSoft SSO'
WHERE title = 'Variphi SSO';
