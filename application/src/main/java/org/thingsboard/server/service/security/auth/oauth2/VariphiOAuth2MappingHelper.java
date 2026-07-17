/**
 * Copyright © 2016-2026 The Thingsboard Authors
 */
package org.thingsboard.server.service.security.auth.oauth2;

import com.fasterxml.jackson.databind.JsonNode;
import lombok.extern.slf4j.Slf4j;
import org.thingsboard.server.common.data.StringUtils;
import org.thingsboard.server.common.data.oauth2.OAuth2Client;
import org.thingsboard.server.dao.oauth2.OAuth2User;

import java.util.Locale;
import java.util.Map;

@Slf4j
public final class VariphiOAuth2MappingHelper {

    public static final String DEFAULT_VIEWER_CUSTOMER_NAME = "Public";
    public static final String VARIPHI_VIEWER_CUSTOMER_NAME = "variphiViewerCustomerName";

    private VariphiOAuth2MappingHelper() {
    }

    public static boolean isEnabled(OAuth2Client oAuth2Client) {
        JsonNode info = oAuth2Client != null ? oAuth2Client.getAdditionalInfo() : null;
        return info != null && info.has(BasicOAuth2ClientMapper.VARIPHI_MAPPER_ENABLED)
                && info.get(BasicOAuth2ClientMapper.VARIPHI_MAPPER_ENABLED).asBoolean(false);
    }

    /** @deprecated use {@link TenantNameValidator#isUnresolvedPattern(String)} */
    public static boolean isUnresolvedTenantName(String tenantName) {
        return TenantNameValidator.isUnresolvedPattern(tenantName);
    }

    public static MappingResult resolve(OAuth2Client oAuth2Client, Map<String, Object> attributes) {
        if (!isEnabled(oAuth2Client) || attributes == null) {
            return MappingResult.disabled();
        }
        JsonNode info = oAuth2Client.getAdditionalInfo();
        String userTypeClaim = claimName(info, BasicOAuth2ClientMapper.VARIPHI_USER_TYPE_CLAIM, "user_type");
        String clientIdClaim = claimName(info, BasicOAuth2ClientMapper.VARIPHI_CLIENT_ID_CLAIM, "client_id");
        String tenantNameClaim = claimName(info, BasicOAuth2ClientMapper.VARIPHI_TENANT_NAME_CLAIM, "client_id");

        String userType = stringClaim(attributes, userTypeClaim);
        if (StringUtils.isEmpty(userType)) {
            userType = resolveUserTypeFromRoleAttribute(attributes);
        }
        String clientId = stringClaim(attributes, clientIdClaim);
        if (StringUtils.isEmpty(clientId)) {
            clientId = stringClaim(attributes, tenantNameClaim);
        }
        if (StringUtils.isEmpty(clientId)) {
            clientId = stringClaim(attributes, "customer");
        }
        if (StringUtils.isEmpty(clientId)) {
            return MappingResult.missingClaims();
        }
        if (!TenantNameValidator.isValidTenantName(clientId)) {
            return MappingResult.invalidTenantName();
        }
        String customerName = resolveAsViewer(userType) ? viewerCustomerName(info) : null;
        return MappingResult.resolved(new VariphiClaims(clientId, userType, customerName));
    }

    /** Applies resolved claims to OAuth2User for provisioning only. */
    public static void applyClaims(OAuth2User oauth2User, VariphiClaims claims) {
        if (oauth2User == null || claims == null) {
            return;
        }
        oauth2User.setTenantName(claims.getTenantName());
        if (StringUtils.isEmpty(claims.getCustomerName())) {
            oauth2User.setCustomerName(null);
            oauth2User.setCustomerId(null);
        } else {
            oauth2User.setCustomerName(claims.getCustomerName());
        }
    }

    public static boolean isViewer(String userType) {
        if (StringUtils.isEmpty(userType)) {
            return false;
        }
        String normalized = userType.trim().toLowerCase(Locale.ROOT);
        return normalized.equals("viewer")
                || normalized.equals("customer")
                || normalized.equals("customer_user")
                || normalized.equals("user");
    }

    public static boolean isAdmin(String userType) {
        if (StringUtils.isEmpty(userType)) {
            return true;
        }
        String normalized = userType.trim().toLowerCase(Locale.ROOT);
        return normalized.equals("admin")
                || normalized.equals("administrator")
                || normalized.equals("tenant_admin")
                || normalized.equals("tenantadmin");
    }

    public static boolean resolveAsViewer(String userType) {
        if (StringUtils.isEmpty(userType)) {
            return false;
        }
        String upper = userType.trim().toUpperCase(Locale.ROOT);
        if (upper.equals("VIEWER") || upper.equals("CUSTOMER") || upper.equals("CUSTOMER_USER")) {
            return true;
        }
        if (upper.equals("ADMIN") || upper.equals("ADMINISTRATOR") || upper.equals("TENANT_ADMIN")) {
            return false;
        }
        return isViewer(userType);
    }

    private static String viewerCustomerName(JsonNode info) {
        if (info != null && info.has(VARIPHI_VIEWER_CUSTOMER_NAME)) {
            String configured = info.get(VARIPHI_VIEWER_CUSTOMER_NAME).asText();
            if (!StringUtils.isEmpty(configured)) {
                return configured;
            }
        }
        return DEFAULT_VIEWER_CUSTOMER_NAME;
    }

    private static String claimName(JsonNode info, String key, String fallback) {
        if (info != null && info.has(key)) {
            String value = info.get(key).asText();
            if (!StringUtils.isEmpty(value)) {
                return value;
            }
        }
        return fallback;
    }

    private static String resolveUserTypeFromRoleAttribute(Map<String, Object> attributes) {
        String role = stringClaim(attributes, "role");
        if (StringUtils.isEmpty(role)) {
            return null;
        }
        if ("admin".equalsIgnoreCase(role)) {
            return "ADMIN";
        }
        return "VIEWER";
    }

    private static String stringClaim(Map<String, Object> attributes, String key) {
        Object value = attributes.get(key);
        if (value == null) {
            return null;
        }
        return String.valueOf(value);
    }
}
