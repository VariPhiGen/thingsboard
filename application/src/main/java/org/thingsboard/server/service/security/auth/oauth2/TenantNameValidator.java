/**
 * Copyright © 2016-2026 The Thingsboard Authors
 */
package org.thingsboard.server.service.security.auth.oauth2;

import org.thingsboard.server.common.data.StringUtils;

public final class TenantNameValidator {

    private static final int MAX_TENANT_NAME_LENGTH = 255;
    private static final String UNRESOLVED_PLACEHOLDER_PREFIX = "%{";

    private TenantNameValidator() {
    }

    public static boolean isUnresolvedPattern(String tenantName) {
        return StringUtils.isEmpty(tenantName) || tenantName.contains(UNRESOLVED_PLACEHOLDER_PREFIX);
    }

    public static boolean isValidTenantName(String tenantName) {
        if (StringUtils.isEmpty(tenantName) || isUnresolvedPattern(tenantName)) {
            return false;
        }
        String trimmed = tenantName.trim();
        if (trimmed.isEmpty() || trimmed.length() > MAX_TENANT_NAME_LENGTH) {
            return false;
        }
        for (int i = 0; i < trimmed.length(); i++) {
            if (Character.isISOControl(trimmed.charAt(i))) {
                return false;
            }
        }
        return true;
    }
}
