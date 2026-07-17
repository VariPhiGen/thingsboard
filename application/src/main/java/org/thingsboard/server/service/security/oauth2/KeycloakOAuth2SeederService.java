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
package org.thingsboard.server.service.security.oauth2;

import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.thingsboard.common.util.JacksonUtil;
import org.thingsboard.server.common.data.domain.Domain;
import org.thingsboard.server.common.data.id.TenantId;
import org.thingsboard.server.common.data.oauth2.OAuth2BasicMapperConfig;
import org.thingsboard.server.common.data.oauth2.OAuth2Client;
import org.thingsboard.server.common.data.oauth2.OAuth2MapperConfig;
import org.thingsboard.server.common.data.oauth2.MapperType;
import org.thingsboard.server.common.data.oauth2.TenantNameStrategyType;
import org.thingsboard.server.dao.domain.DomainService;
import org.thingsboard.server.dao.oauth2.OAuth2ClientService;
import org.thingsboard.server.service.security.auth.oauth2.BasicOAuth2ClientMapper;
import org.thingsboard.server.service.security.auth.oauth2.VariphiOAuth2MappingHelper;

import java.util.Arrays;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Slf4j
public class KeycloakOAuth2SeederService {

    private final OAuth2ClientService oAuth2ClientService;
    private final DomainService domainService;

    @Value("${security.oauth2.keycloak.enabled:false}")
    private boolean keycloakSsoEnabled;
    @Value("${security.oauth2.keycloak.title:Variphi SSO}")
    private String keycloakSsoTitle;
    @Value("${security.oauth2.keycloak.client-id:}")
    private String keycloakClientId;
    @Value("${security.oauth2.keycloak.client-secret:}")
    private String keycloakClientSecret;
    @Value("${security.oauth2.keycloak.issuer-uri:http://localhost:8081/realms/things}")
    private String keycloakIssuerUri;
    @Value("${security.oauth2.keycloak.auth-issuer-uri:}")
    private String keycloakAuthIssuerUri;
    @Value("${security.oauth2.keycloak.domain-name:localhost:9090}")
    private String keycloakDomainName;
    @Value("${security.oauth2.keycloak.scopes:openid,email,profile}")
    private String keycloakScopes;
    @Value("${security.oauth2.keycloak.user-type-claim:user_type}")
    private String keycloakUserTypeClaim;
    @Value("${security.oauth2.keycloak.client-id-claim:client_id}")
    private String keycloakClientIdClaim;
    @Value("${security.oauth2.keycloak.tenant-name-claim:client_id}")
    private String keycloakTenantNameClaim;

    public void seedIfMissing() throws Exception {
        if (!keycloakSsoEnabled) {
            log.info("Keycloak SSO seeding is disabled (security.oauth2.keycloak.enabled=false). Skipping.");
            return;
        }
        if (StringUtils.isBlank(keycloakClientId) || StringUtils.isBlank(keycloakClientSecret) || StringUtils.isBlank(keycloakIssuerUri)) {
            log.warn("Keycloak SSO is enabled but client-id/client-secret/issuer-uri are not fully configured. Skipping seeding.");
            return;
        }

        TenantId tenantId = TenantId.SYS_TENANT_ID;

        boolean alreadyExists = oAuth2ClientService.findOAuth2ClientsByTenantId(tenantId).stream()
                .anyMatch(client -> keycloakSsoTitle.equals(client.getTitle()));
        if (alreadyExists) {
            log.info("Keycloak OAuth2 client [{}] already exists. Skipping seeding.", keycloakSsoTitle);
            return;
        }

        OAuth2Client client = buildOAuth2Client(tenantId);
        OAuth2Client savedClient = oAuth2ClientService.saveOAuth2Client(tenantId, client);

        Domain domain = new Domain();
        domain.setTenantId(tenantId);
        domain.setName(keycloakDomainName);
        domain.setOauth2Enabled(true);
        domain.setPropagateToEdge(false);
        Domain savedDomain = domainService.saveDomain(tenantId, domain);
        domainService.updateOauth2Clients(tenantId, savedDomain.getId(), List.of(savedClient.getId()));

        log.info("Seeded Keycloak OAuth2 client [{}] (clientId={}) on domain [{}] for SSO login.",
                keycloakSsoTitle, keycloakClientId, keycloakDomainName);
    }

    /**
     * Keeps the DB OAuth2 client aligned with env (issuer/domain/secret) after hostname or gateway changes.
     */
    public void syncOAuth2ClientConfig() throws Exception {
        if (!keycloakSsoEnabled) {
            return;
        }
        if (StringUtils.isBlank(keycloakClientId) || StringUtils.isBlank(keycloakClientSecret) || StringUtils.isBlank(keycloakIssuerUri)) {
            return;
        }

        TenantId tenantId = TenantId.SYS_TENANT_ID;
        Optional<OAuth2Client> existing = oAuth2ClientService.findOAuth2ClientsByTenantId(tenantId).stream()
                .filter(client -> keycloakSsoTitle.equals(client.getTitle()))
                .findFirst();
        if (existing.isEmpty()) {
            return;
        }

        OAuth2Client client = existing.get();
        OAuth2Client updated = buildOAuth2Client(tenantId);
        updated.setId(client.getId());
        updated.setCreatedTime(client.getCreatedTime());
        oAuth2ClientService.saveOAuth2Client(tenantId, updated);
        log.info("Synced Keycloak OAuth2 client [{}] endpoints to issuer {}", keycloakSsoTitle, keycloakIssuerUri);
    }

    public void syncVariphiMapperConfig() throws Exception {
        if (!keycloakSsoEnabled) {
            return;
        }
        TenantId tenantId = TenantId.SYS_TENANT_ID;
        Optional<OAuth2Client> existing = oAuth2ClientService.findOAuth2ClientsByTenantId(tenantId).stream()
                .filter(client -> keycloakSsoTitle.equals(client.getTitle()))
                .findFirst();
        if (existing.isEmpty()) {
            return;
        }

        OAuth2Client client = existing.get();
        ObjectNode additionalInfo = client.getAdditionalInfo() != null
                ? (ObjectNode) client.getAdditionalInfo().deepCopy()
                : JacksonUtil.newObjectNode();
        additionalInfo.put("providerName", "Keycloak");
        additionalInfo.put(BasicOAuth2ClientMapper.VARIPHI_MAPPER_ENABLED, true);
        additionalInfo.put(BasicOAuth2ClientMapper.VARIPHI_USER_TYPE_CLAIM, keycloakUserTypeClaim);
        additionalInfo.put(BasicOAuth2ClientMapper.VARIPHI_CLIENT_ID_CLAIM, keycloakClientIdClaim);
        additionalInfo.put(BasicOAuth2ClientMapper.VARIPHI_TENANT_NAME_CLAIM, keycloakTenantNameClaim);
        additionalInfo.put(VariphiOAuth2MappingHelper.VARIPHI_VIEWER_CUSTOMER_NAME,
                VariphiOAuth2MappingHelper.DEFAULT_VIEWER_CUSTOMER_NAME);
        client.setAdditionalInfo(additionalInfo);

        OAuth2MapperConfig mapperConfig = client.getMapperConfig();
        if (mapperConfig != null && mapperConfig.getBasic() != null) {
            OAuth2BasicMapperConfig basic = mapperConfig.getBasic().toBuilder()
                    .tenantNameStrategy(TenantNameStrategyType.CUSTOM)
                    .tenantNamePattern("%{" + keycloakTenantNameClaim + "}")
                    .customerNamePattern("")
                    .build();
            mapperConfig.setBasic(basic);
        }
        oAuth2ClientService.saveOAuth2Client(tenantId, client);
        log.info("Synced Variphi Keycloak OAuth2 mapper for [{}] (admin→tenant admin, viewer→customer by client_id).",
                keycloakSsoTitle);
    }

    private OAuth2Client buildOAuth2Client(TenantId tenantId) {
        String issuer = keycloakIssuerUri.replaceAll("/+$", "");
        String authIssuer = StringUtils.isBlank(keycloakAuthIssuerUri) ? issuer : keycloakAuthIssuerUri.replaceAll("/+$", "");
        List<String> scopes = Arrays.stream(keycloakScopes.split(","))
                .map(String::trim).filter(s -> !s.isEmpty()).toList();

        ObjectNode additionalInfo = JacksonUtil.newObjectNode();
        additionalInfo.put("providerName", "Keycloak");
        additionalInfo.put(BasicOAuth2ClientMapper.VARIPHI_MAPPER_ENABLED, true);
        additionalInfo.put(BasicOAuth2ClientMapper.VARIPHI_USER_TYPE_CLAIM, keycloakUserTypeClaim);
        additionalInfo.put(BasicOAuth2ClientMapper.VARIPHI_CLIENT_ID_CLAIM, keycloakClientIdClaim);
        additionalInfo.put(BasicOAuth2ClientMapper.VARIPHI_TENANT_NAME_CLAIM, keycloakTenantNameClaim);
        additionalInfo.put(VariphiOAuth2MappingHelper.VARIPHI_VIEWER_CUSTOMER_NAME,
                VariphiOAuth2MappingHelper.DEFAULT_VIEWER_CUSTOMER_NAME);

        OAuth2Client client = new OAuth2Client();
        client.setTenantId(tenantId);
        client.setTitle(keycloakSsoTitle);
        client.setClientId(keycloakClientId);
        client.setClientSecret(keycloakClientSecret);
        client.setAuthorizationUri(authIssuer + "/protocol/openid-connect/auth");
        client.setAccessTokenUri(issuer + "/protocol/openid-connect/token");
        client.setUserInfoUri(issuer + "/protocol/openid-connect/userinfo");
        client.setJwkSetUri(issuer + "/protocol/openid-connect/certs");
        client.setScope(scopes);
        client.setUserNameAttributeName("email");
        client.setClientAuthenticationMethod("POST");
        client.setLoginButtonLabel(keycloakSsoTitle);
        client.setLoginButtonIcon("login");
        client.setAdditionalInfo(additionalInfo);
        client.setMapperConfig(OAuth2MapperConfig.builder()
                .allowUserCreation(true)
                .activateUser(true)
                .type(MapperType.BASIC)
                .basic(OAuth2BasicMapperConfig.builder()
                        .emailAttributeKey("email")
                        .firstNameAttributeKey("given_name")
                        .lastNameAttributeKey("family_name")
                        .tenantNameStrategy(TenantNameStrategyType.CUSTOM)
                        .tenantNamePattern("%{" + keycloakTenantNameClaim + "}")
                        .customerNamePattern("")
                        .alwaysFullScreen(false)
                        .build())
                .build());
        return client;
    }
}
