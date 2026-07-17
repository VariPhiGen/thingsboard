/**
 * Copyright © 2016-2026 The Thingsboard Authors
 */
package org.thingsboard.server.service.security.auth.oauth2;

import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.oauth2.client.authentication.OAuth2AuthenticationToken;
import org.springframework.stereotype.Service;
import org.thingsboard.server.common.data.oauth2.OAuth2MapperConfig;
import org.thingsboard.server.common.data.oauth2.OAuth2Client;
import org.thingsboard.server.dao.oauth2.OAuth2User;
import org.thingsboard.server.queue.util.TbCoreComponent;
import org.thingsboard.server.service.security.model.SecurityUser;

import java.util.Map;

@Service(value = "basicOAuth2ClientMapper")
@Slf4j
@TbCoreComponent
public class BasicOAuth2ClientMapper extends AbstractOAuth2ClientMapper implements OAuth2ClientMapper {

    public static final String VARIPHI_MAPPER_ENABLED = "variphiMapperEnabled";
    public static final String VARIPHI_USER_TYPE_CLAIM = "variphiUserTypeClaim";
    public static final String VARIPHI_CLIENT_ID_CLAIM = "variphiClientIdClaim";
    public static final String VARIPHI_TENANT_NAME_CLAIM = "variphiTenantNameClaim";

    @Override
    public SecurityUser getOrCreateUserByClientPrincipal(HttpServletRequest request, OAuth2AuthenticationToken token, String providerAccessToken, OAuth2Client oAuth2Client) {
        OAuth2MapperConfig config = oAuth2Client.getMapperConfig();
        Map<String, Object> attributes = token.getPrincipal().getAttributes();
        String email = BasicMapperUtils.getStringAttributeByKey(attributes, config.getBasic().getEmailAttributeKey());

        if (VariphiOAuth2MappingHelper.isEnabled(oAuth2Client)) {
            return handleVariphiAuth(email, attributes, config, oAuth2Client);
        }

        OAuth2User oauth2User = BasicMapperUtils.getOAuth2User(email, attributes, config);
        return getOrCreateSecurityUserFromOAuth2User(oauth2User, oAuth2Client);
    }
}
