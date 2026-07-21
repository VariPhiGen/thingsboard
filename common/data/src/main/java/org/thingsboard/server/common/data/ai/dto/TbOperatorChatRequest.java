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
package org.thingsboard.server.common.data.ai.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.util.List;
import java.util.UUID;

public record TbOperatorChatRequest(
        @Schema(
                requiredMode = Schema.RequiredMode.REQUIRED,
                description = "Target device ID used to ground the operator answer",
                example = "3877b730-81cb-11f1-a760-b3ba4cbe1b98"
        )
        @NotNull UUID deviceId,

        @Schema(
                requiredMode = Schema.RequiredMode.REQUIRED,
                description = "Dashboard ID that hosts the chatbot widget",
                example = "09c06030-81cc-11f1-a760-b3ba4cbe1b98"
        )
        @NotNull UUID dashboardId,

        @Schema(
                requiredMode = Schema.RequiredMode.REQUIRED,
                description = "Tenant AI model ID that should answer the question",
                example = "d78b28f0-810f-11f1-a760-b3ba4cbe1b98"
        )
        @NotNull UUID aiModelId,

        @Schema(
                requiredMode = Schema.RequiredMode.NOT_REQUIRED,
                description = "Conversation identifier. If absent, the server creates one."
        )
        String conversationId,

        @Schema(
                requiredMode = Schema.RequiredMode.REQUIRED,
                description = "Current operator question",
                example = "Is DG SET1 running and what should I check next?"
        )
        @NotBlank String message,

        @Schema(
                requiredMode = Schema.RequiredMode.NOT_REQUIRED,
                description = "Optional recent messages used to restore short context after a page refresh"
        )
        @Valid List<TbOperatorChatMessage> messages
) {
}
