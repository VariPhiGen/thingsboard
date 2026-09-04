-- Point Virtuoso TB OAuth2 client at Keycloak realm viot + client viot.
-- Run: PGPASSWORD=... psql -h 13.206.196.162 -U variphi -d tb_virtuoso -f migrate-tb-oauth2-viot-realm.sql

\set issuer_base 'https://auth.virtuosonetsoft.variphi.com/realms/viot'
\set client_id 'viot'
\set client_secret 'cfab5cc2-8039-4547-a5cf-df757d01a247'

UPDATE oauth2_client
SET
  client_id = :'client_id',
  client_secret = :'client_secret',
  authorization_uri = :'issuer_base' || '/protocol/openid-connect/auth',
  token_uri = :'issuer_base' || '/protocol/openid-connect/token',
  user_info_uri = :'issuer_base' || '/protocol/openid-connect/userinfo',
  jwk_set_uri = :'issuer_base' || '/protocol/openid-connect/certs',
  title = 'Virtuoso IoT SSO',
  login_button_label = 'Virtuoso IoT SSO'
WHERE title IN ('Virtuoso NetSoft SSO', 'Variphi SSO', 'Virtuoso IoT SSO');
