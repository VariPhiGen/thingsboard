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
package org.thingsboard.server.config;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import org.thingsboard.server.service.install.SystemDataLoaderService;

/**
 * Ensures Keycloak OAuth2 client + domain exist when TB starts against an already-provisioned DB
 * (install profile only seeds on first install).
 */
@Component
@ConditionalOnProperty(name = "security.oauth2.keycloak.enabled", havingValue = "true")
@RequiredArgsConstructor
@Slf4j
public class KeycloakOAuth2StartupSeeder {

    private final SystemDataLoaderService systemDataLoaderService;

    @Value("${install:false}")
    private boolean installProfile;

    @EventListener(ApplicationReadyEvent.class)
    public void onReady() {
        if (installProfile) {
            return;
        }
        try {
            systemDataLoaderService.createKeycloakOAuth2Client();
        } catch (Exception e) {
            log.error("Failed to seed Keycloak OAuth2 client on startup", e);
        }
    }
}
