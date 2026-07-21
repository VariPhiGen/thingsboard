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

import java.util.List;
import java.util.Map;

public record TbOperatorChatResponse(
        @Schema(description = "Conversation identifier used by subsequent chat requests")
        String conversationId,

        @Schema(description = "Generated chatbot answer shown to the operator")
        String answer,

        @Schema(description = "Response generation timestamp in milliseconds")
        long timestamp,

        @Schema(description = "Latest grounded device data used for the answer")
        DeviceSnapshot deviceSnapshot,

        @Schema(description = "Current active alarms considered by the chatbot")
        List<AlarmSummary> activeAlarms,

        @Schema(description = "Short list of data sources used to generate the answer")
        List<String> sources
) {

    public record DeviceSnapshot(
            @Schema(description = "Device display name")
            String deviceName,

            @Schema(description = "Dashboard title")
            String dashboardTitle,

            @Schema(description = "Latest telemetry timestamp used by the chatbot")
            long lastTelemetryTs,

            @Schema(description = "Latest normalized values shown to operators")
            Map<String, String> values
    ) {
    }

    public record AlarmSummary(
            @Schema(description = "Alarm severity")
            String severity,

            @Schema(description = "Alarm type")
            String type,

            @Schema(description = "Alarm status")
            String status,

            @Schema(description = "Operator-friendly alarm details")
            String details
    ) {
    }

}
