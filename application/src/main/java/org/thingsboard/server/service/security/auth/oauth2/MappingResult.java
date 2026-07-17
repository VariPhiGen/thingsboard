/**
 * Copyright © 2016-2026 The Thingsboard Authors
 */
package org.thingsboard.server.service.security.auth.oauth2;

import lombok.Getter;

@Getter
public final class MappingResult {

    public enum Status {
        RESOLVED,
        MISSING_CLAIMS,
        INVALID_TENANT_NAME,
        DISABLED
    }

    private static final String MISSING_CLAIMS_MESSAGE =
            "Tenant assignment missing from identity provider. Contact your administrator.";
    private static final String INVALID_TENANT_MESSAGE =
            "Invalid tenant assignment from identity provider. Contact your administrator.";

    private final Status status;
    private final VariphiClaims claims;

    private MappingResult(Status status, VariphiClaims claims) {
        this.status = status;
        this.claims = claims;
    }

    public static MappingResult disabled() {
        return new MappingResult(Status.DISABLED, null);
    }

    public static MappingResult missingClaims() {
        return new MappingResult(Status.MISSING_CLAIMS, null);
    }

    public static MappingResult invalidTenantName() {
        return new MappingResult(Status.INVALID_TENANT_NAME, null);
    }

    public static MappingResult resolved(VariphiClaims claims) {
        return new MappingResult(Status.RESOLVED, claims);
    }

    public boolean isResolved() {
        return status == Status.RESOLVED && claims != null;
    }

    public String getUserMessage() {
        return switch (status) {
            case MISSING_CLAIMS -> MISSING_CLAIMS_MESSAGE;
            case INVALID_TENANT_NAME -> INVALID_TENANT_MESSAGE;
            default -> MISSING_CLAIMS_MESSAGE;
        };
    }
}
