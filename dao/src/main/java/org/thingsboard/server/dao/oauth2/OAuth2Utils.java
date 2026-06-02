/**
 * Copyright © 2016-2026 The Thingsboard Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.thingsboard.server.dao.oauth2;

import org.thingsboard.server.common.data.oauth2.OAuth2ClientLoginInfo;
import org.thingsboard.server.common.data.oauth2.OAuth2Client;

public class OAuth2Utils {
    public static final String OAUTH2_AUTHORIZATION_PATH_TEMPLATE = "/oauth2/authorization/%s";
    private static final String OIDC_AUTH_SUFFIX = "/protocol/openid-connect/auth";

    public static OAuth2ClientLoginInfo toClientLoginInfo(OAuth2Client registration) {
        OAuth2ClientLoginInfo client = new OAuth2ClientLoginInfo();
        client.setName(registration.getLoginButtonLabel());
        client.setUrl(String.format(OAUTH2_AUTHORIZATION_PATH_TEMPLATE, registration.getUuidId().toString()));
        client.setIcon(registration.getLoginButtonIcon());
        client.setLogoutUrl(toOidcLogoutUrl(registration));
        return client;
    }

    // For OpenID Connect providers (e.g. Keycloak), derive the RP-initiated logout (end_session) URL
    // from the browser-facing authorization URI so the UI can end the IdP session on logout.
    private static String toOidcLogoutUrl(OAuth2Client registration) {
        String authUri = registration.getAuthorizationUri();
        if (authUri != null && authUri.endsWith(OIDC_AUTH_SUFFIX)) {
            String base = authUri.substring(0, authUri.length() - "/auth".length());
            return base + "/logout?client_id=" + registration.getClientId();
        }
        return null;
    }

}
