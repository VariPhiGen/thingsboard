/**
 * Copyright © 2016-2026 The Thingsboard Authors
 */
package org.thingsboard.server.service.security.auth.oauth2;

import lombok.Value;

@Value
public class VariphiClaims {
    String tenantName;
    String userType;
    String customerName;
}
