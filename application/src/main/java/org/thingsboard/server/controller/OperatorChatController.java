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
package org.thingsboard.server.controller;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.request.async.DeferredResult;
import org.thingsboard.server.common.data.ai.dto.TbOperatorChatRequest;
import org.thingsboard.server.common.data.ai.dto.TbOperatorChatResponse;
import org.thingsboard.server.common.data.id.DashboardId;
import org.thingsboard.server.common.data.id.DeviceId;
import org.thingsboard.server.config.annotations.ApiOperation;
import org.thingsboard.server.queue.util.TbCoreComponent;
import org.thingsboard.server.service.ai.OperatorChatService;
import org.thingsboard.server.service.security.permission.Operation;

import java.util.UUID;

import static org.thingsboard.server.controller.ControllerConstants.TENANT_OR_CUSTOMER_AUTHORITY_PARAGRAPH;

@Validated
@RestController
@TbCoreComponent
@RequiredArgsConstructor
@RequestMapping("/api/chatbot")
class OperatorChatController extends BaseController {

    private final OperatorChatService operatorChatService;

    @ApiOperation(
            value = "Ask the operator chatbot (chatWithOperatorAssistant)",
            notes = "Returns a grounded chatbot answer using the selected device dashboard context, latest telemetry, and active alarms. " +
                    TENANT_OR_CUSTOMER_AUTHORITY_PARAGRAPH
    )
    @PreAuthorize("hasAnyAuthority('TENANT_ADMIN', 'CUSTOMER_USER')")
    @PostMapping("/operator")
    public DeferredResult<TbOperatorChatResponse> chatWithOperatorAssistant(
            @io.swagger.v3.oas.annotations.parameters.RequestBody(
                    description = "Operator chatbot request body",
                    required = true
            )
            @Valid @RequestBody TbOperatorChatRequest request
    ) throws Exception {
        DeviceId deviceId = new DeviceId(request.deviceId());
        DashboardId dashboardId = new DashboardId(request.dashboardId());
        checkDeviceId(deviceId, Operation.READ);
        checkDashboardId(dashboardId, Operation.READ);
        return wrapFuture(operatorChatService.chat(getCurrentUser(), deviceId, dashboardId, request), 60000L);
    }

}
