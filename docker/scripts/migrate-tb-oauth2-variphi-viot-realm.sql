-- Point Variphi TB OAuth2 client at gateway Keycloak realm viot + client viot.
-- Run: PGPASSWORD=... psql -h 13.206.196.162 -U variphi -d tb -f migrate-tb-oauth2-variphi-viot-realm.sql

\set issuer_base 'https://api.edge.variphi.com/auth/realms/viot'
\set client_id 'viot'
\set client_secret '07efad71-2d29-4df2-bfe7-6fa998ddff68'

UPDATE oauth2_client
SET
  client_id = :'client_id',
  client_secret = :'client_secret',
  authorization_uri = :'issuer_base' || '/protocol/openid-connect/auth',
  token_uri = :'issuer_base' || '/protocol/openid-connect/token',
  user_info_uri = :'issuer_base' || '/protocol/openid-connect/userinfo',
  jwk_set_uri = :'issuer_base' || '/protocol/openid-connect/certs',
  title = 'Variphi SSO',
  login_button_label = 'Variphi SSO'
WHERE title IN ('Variphi SSO', 'Virtuoso NetSoft SSO', 'Virtuoso IoT SSO');
