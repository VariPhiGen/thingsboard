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
package org.thingsboard.server.service.ai;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.google.common.util.concurrent.FluentFuture;
import com.google.common.util.concurrent.Futures;
import com.google.common.util.concurrent.ListenableFuture;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.request.ChatRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.thingsboard.common.util.JacksonUtil;
import org.thingsboard.server.common.data.Dashboard;
import org.thingsboard.server.common.data.Device;
import org.thingsboard.server.common.data.StringUtils;
import org.thingsboard.server.common.data.ai.AiModel;
import org.thingsboard.server.common.data.ai.dto.TbOperatorChatMessage;
import org.thingsboard.server.common.data.ai.dto.TbOperatorChatRequest;
import org.thingsboard.server.common.data.ai.dto.TbOperatorChatResponse;
import org.thingsboard.server.common.data.ai.model.chat.AiChatModelConfig;
import org.thingsboard.server.common.data.alarm.AlarmInfo;
import org.thingsboard.server.common.data.alarm.AlarmQuery;
import org.thingsboard.server.common.data.alarm.AlarmSearchStatus;
import org.thingsboard.server.common.data.exception.ThingsboardErrorCode;
import org.thingsboard.server.common.data.exception.ThingsboardException;
import org.thingsboard.server.common.data.id.AiModelId;
import org.thingsboard.server.common.data.id.DashboardId;
import org.thingsboard.server.common.data.id.DeviceId;
import org.thingsboard.server.common.data.id.TenantId;
import org.thingsboard.server.common.data.kv.TsKvEntry;
import org.thingsboard.server.common.data.page.TimePageLink;
import org.thingsboard.server.dao.ai.AiModelService;
import org.thingsboard.server.dao.alarm.AlarmService;
import org.thingsboard.server.dao.dashboard.DashboardService;
import org.thingsboard.server.dao.device.DeviceService;
import org.thingsboard.server.dao.timeseries.TimeseriesService;
import org.thingsboard.server.service.security.model.SecurityUser;

import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import static com.google.common.util.concurrent.MoreExecutors.directExecutor;

@Service
@Slf4j
class DefaultOperatorChatService implements OperatorChatService {

    private static final List<String> CONTEXT_KEYS = List.of(
            "dg_status", "common_alarm", "power_kw", "engine_rpm", "coolant_temp", "oil_pressure",
            "fuel_level", "battery_voltage", "frequency", "ai_status", "severity", "summary",
            "maintenance_recommendation", "health_score", "failure_risk_pct", "rul_hours",
            "predicted_coolant_1h"
    );

    private static final Map<String, String> DISPLAY_NAMES = Map.ofEntries(
            Map.entry("dg_status", "DG Status"),
            Map.entry("common_alarm", "Common Alarm"),
            Map.entry("power_kw", "Power (kW)"),
            Map.entry("engine_rpm", "Engine RPM"),
            Map.entry("coolant_temp", "Coolant Temperature"),
            Map.entry("oil_pressure", "Oil Pressure"),
            Map.entry("fuel_level", "Fuel Level"),
            Map.entry("battery_voltage", "Battery Voltage"),
            Map.entry("frequency", "Frequency"),
            Map.entry("ai_status", "AI Status"),
            Map.entry("severity", "AI Severity"),
            Map.entry("summary", "AI Summary"),
            Map.entry("maintenance_recommendation", "Maintenance Recommendation"),
            Map.entry("health_score", "Health Score"),
            Map.entry("failure_risk_pct", "Failure Risk %"),
            Map.entry("rul_hours", "RUL Hours"),
            Map.entry("predicted_coolant_1h", "Predicted Coolant 1h")
    );

    private static final List<String> SOURCES = List.of("latest telemetry", "active alarms", "AI summary telemetry");
    private static final Pattern UNSUPPORTED_ACTIONS = Pattern.compile(
            "(password|token|secret|api key|credential|delete|drop|create dashboard|edit dashboard|rule chain|sql|ssh|shell|restart)",
            Pattern.CASE_INSENSITIVE
    );

    private final AiModelService aiModelService;
    private final AiChatModelService aiChatModelService;
    private final DeviceService deviceService;
    private final DashboardService dashboardService;
    private final TimeseriesService timeseriesService;
    private final AlarmService alarmService;
    private final Cache<ConversationKey, ConversationState> conversations;
    private final Cache<RateLimitKey, RateLimitState> rateLimits;
    private final int maxConversationMessages;
    private final int maxHistoryMessagesFromClient;
    private final int maxMessageChars;
    private final int rateLimitCount;
    private final long rateLimitWindowMs;
    private final long minRequestIntervalMs;

    DefaultOperatorChatService(AiModelService aiModelService,
                               AiChatModelService aiChatModelService,
                               DeviceService deviceService,
                               DashboardService dashboardService,
                               TimeseriesService timeseriesService,
                               AlarmService alarmService,
                               @Value("${chatbot.conversation.ttl-minutes:30}") int conversationTtlMinutes,
                               @Value("${chatbot.conversation.max-size:10000}") int conversationCacheMaxSize,
                               @Value("${chatbot.conversation.max-messages:12}") int maxConversationMessages,
                               @Value("${chatbot.conversation.max-client-history:6}") int maxHistoryMessagesFromClient,
                               @Value("${chatbot.request.max-message-chars:1200}") int maxMessageChars,
                               @Value("${chatbot.rate-limit.count:12}") int rateLimitCount,
                               @Value("${chatbot.rate-limit.window-ms:300000}") long rateLimitWindowMs,
                               @Value("${chatbot.rate-limit.min-interval-ms:1500}") long minRequestIntervalMs) {
        this.aiModelService = aiModelService;
        this.aiChatModelService = aiChatModelService;
        this.deviceService = deviceService;
        this.dashboardService = dashboardService;
        this.timeseriesService = timeseriesService;
        this.alarmService = alarmService;
        this.conversations = Caffeine.newBuilder()
                .expireAfterAccess(conversationTtlMinutes, TimeUnit.MINUTES)
                .maximumSize(conversationCacheMaxSize)
                .build();
        this.rateLimits = Caffeine.newBuilder()
                .expireAfterAccess(Math.max(1L, rateLimitWindowMs * 2L), TimeUnit.MILLISECONDS)
                .maximumSize(conversationCacheMaxSize)
                .build();
        this.maxConversationMessages = maxConversationMessages;
        this.maxHistoryMessagesFromClient = maxHistoryMessagesFromClient;
        this.maxMessageChars = maxMessageChars;
        this.rateLimitCount = rateLimitCount;
        this.rateLimitWindowMs = rateLimitWindowMs;
        this.minRequestIntervalMs = minRequestIntervalMs;
    }

    @Override
    public FluentFuture<TbOperatorChatResponse> chat(SecurityUser currentUser,
                                                     DeviceId deviceId,
                                                     DashboardId dashboardId,
                                                     TbOperatorChatRequest request) {
        try {
            String message = validateMessage(request.message());
            AiChatModelConfig<?> chatModelConfig = resolveChatModel(currentUser.getTenantId(), request);
            Device device = requireDevice(currentUser.getTenantId(), deviceId);
            Dashboard dashboard = requireDashboard(currentUser.getTenantId(), dashboardId);
            String conversationId = StringUtils.isBlank(request.conversationId()) ? UUID.randomUUID().toString() : request.conversationId().trim();
            ConversationKey conversationKey = new ConversationKey(currentUser.getTenantId(), currentUser.getId().getId(), deviceId.getId(), conversationId);
            enforceRateLimit(currentUser, deviceId);

            ListenableFuture<List<TsKvEntry>> telemetryFuture = timeseriesService.findLatest(currentUser.getTenantId(), deviceId, CONTEXT_KEYS);
            return FluentFuture.from(telemetryFuture)
                    .transformAsync(telemetry -> {
                        OperatorContext context = buildContext(currentUser, device, dashboard, telemetry, deviceId);
                        if (isUnsupportedQuestion(message)) {
                            String refusal = unsupportedActionAnswer(context.deviceName());
                            rememberExchange(conversationKey, request.messages(), message, refusal);
                            return Futures.immediateFuture(toResponse(conversationId, refusal, context));
                        }
                        ChatRequest chatRequest = buildChatRequest(conversationKey, request.messages(), message, context);
                        return aiChatModelService.sendChatRequestAsync(chatModelConfig, chatRequest)
                                .transform(chatResponse -> {
                                    String answer = Optional.ofNullable(chatResponse.aiMessage())
                                            .map(AiMessage::text)
                                            .filter(StringUtils::isNotBlank)
                                            .map(String::trim)
                                            .orElseGet(() -> fallbackAnswer(context.deviceName()));
                                    rememberExchange(conversationKey, request.messages(), message, answer);
                                    return toResponse(conversationId, answer, context);
                                }, directExecutor())
                                .catching(Throwable.class, t -> {
                                    log.warn("Operator chatbot model call failed for tenant [{}], device [{}]: {}", currentUser.getTenantId(), deviceId, t.getMessage());
                                    String answer = fallbackAnswer(context.deviceName());
                                    rememberExchange(conversationKey, request.messages(), message, answer);
                                    return toResponse(conversationId, answer, context);
                                }, directExecutor());
                    }, directExecutor());
        } catch (ThingsboardException e) {
            return FluentFuture.from(Futures.immediateFailedFuture(e));
        } catch (Exception e) {
            return FluentFuture.from(Futures.immediateFailedFuture(new ThingsboardException(e.getMessage(), ThingsboardErrorCode.GENERAL)));
        }
    }

    private Device requireDevice(TenantId tenantId, DeviceId deviceId) throws ThingsboardException {
        Device device = deviceService.findDeviceById(tenantId, deviceId);
        if (device == null) {
            throw new ThingsboardException("Device not found", ThingsboardErrorCode.ITEM_NOT_FOUND);
        }
        return device;
    }

    private Dashboard requireDashboard(TenantId tenantId, DashboardId dashboardId) throws ThingsboardException {
        Dashboard dashboard = dashboardService.findDashboardById(tenantId, dashboardId);
        if (dashboard == null) {
            throw new ThingsboardException("Dashboard not found", ThingsboardErrorCode.ITEM_NOT_FOUND);
        }
        return dashboard;
    }

    private AiChatModelConfig<?> resolveChatModel(TenantId tenantId, TbOperatorChatRequest request) throws ThingsboardException {
        AiModelId modelId = new AiModelId(request.aiModelId());
        AiModel model = aiModelService.findAiModelByTenantIdAndId(tenantId, modelId)
                .orElseThrow(() -> new ThingsboardException("AI model not found", ThingsboardErrorCode.ITEM_NOT_FOUND));
        if (!(model.getConfiguration() instanceof AiChatModelConfig<?> chatModelConfig)) {
            throw new ThingsboardException("Selected AI model is not a chat model", ThingsboardErrorCode.BAD_REQUEST_PARAMS);
        }
        return chatModelConfig;
    }

    private String validateMessage(String message) throws ThingsboardException {
        String trimmed = Optional.ofNullable(message).map(String::trim).orElse("");
        if (trimmed.isEmpty()) {
            throw new ThingsboardException("Message must not be empty", ThingsboardErrorCode.BAD_REQUEST_PARAMS);
        }
        if (trimmed.length() > maxMessageChars) {
            throw new ThingsboardException("Message is too long", ThingsboardErrorCode.BAD_REQUEST_PARAMS);
        }
        return trimmed;
    }

    private void enforceRateLimit(SecurityUser currentUser, DeviceId deviceId) throws ThingsboardException {
        long now = System.currentTimeMillis();
        RateLimitKey key = new RateLimitKey(currentUser.getTenantId(), currentUser.getId().getId(), deviceId.getId());
        RateLimitState state = rateLimits.get(key, ignored -> new RateLimitState(now, 0, 0));
        synchronized (state) {
            if (now - state.windowStartedAt > rateLimitWindowMs) {
                state.windowStartedAt = now;
                state.requestCount = 0;
            }
            if (state.lastRequestAt > 0 && now - state.lastRequestAt < minRequestIntervalMs) {
                throw new ThingsboardException("Please wait a moment before sending another question.", ThingsboardErrorCode.TOO_MANY_REQUESTS);
            }
            if (state.requestCount >= rateLimitCount) {
                throw new ThingsboardException("Chat request limit reached. Please retry later.", ThingsboardErrorCode.TOO_MANY_REQUESTS);
            }
            state.requestCount++;
            state.lastRequestAt = now;
        }
    }

    private OperatorContext buildContext(SecurityUser currentUser,
                                         Device device,
                                         Dashboard dashboard,
                                         List<TsKvEntry> telemetry,
                                         DeviceId deviceId) {
        Map<String, String> values = new LinkedHashMap<>();
        long latestTs = 0L;
        Map<String, TsKvEntry> latestByKey = new LinkedHashMap<>();
        for (TsKvEntry entry : telemetry) {
            latestByKey.put(entry.getKey(), entry);
            latestTs = Math.max(latestTs, entry.getTs());
        }
        for (String key : CONTEXT_KEYS) {
            values.put(DISPLAY_NAMES.getOrDefault(key, key), normalizeValue(latestByKey.get(key)));
        }

        List<TbOperatorChatResponse.AlarmSummary> activeAlarms = loadActiveAlarms(currentUser.getTenantId(), deviceId);
        String contextJson = JacksonUtil.toString(Map.of(
                "deviceName", device.getName(),
                "dashboardTitle", dashboard.getTitle(),
                "timestamp", latestTs > 0 ? Instant.ofEpochMilli(latestTs).toString() : "N/A",
                "telemetry", values,
                "activeAlarms", activeAlarms
        ));

        TbOperatorChatResponse.DeviceSnapshot snapshot = new TbOperatorChatResponse.DeviceSnapshot(
                device.getName(),
                dashboard.getTitle(),
                latestTs,
                values
        );
        return new OperatorContext(device.getName(), dashboard.getTitle(), contextJson, snapshot, activeAlarms);
    }

    private List<TbOperatorChatResponse.AlarmSummary> loadActiveAlarms(TenantId tenantId, DeviceId deviceId) {
        List<TbOperatorChatResponse.AlarmSummary> alarms = new ArrayList<>();
        AlarmQuery query = new AlarmQuery(deviceId, new TimePageLink(10, 0), AlarmSearchStatus.ACTIVE, null, null, true);
        for (AlarmInfo alarm : alarmService.findAlarms(tenantId, query).getData()) {
            alarms.add(new TbOperatorChatResponse.AlarmSummary(
                    String.valueOf(alarm.getSeverity()),
                    alarm.getType(),
                    String.valueOf(alarm.getStatus()),
                    formatAlarmDetails(alarm)
            ));
        }
        return alarms;
    }

    private ChatRequest buildChatRequest(ConversationKey conversationKey,
                                         List<TbOperatorChatMessage> clientMessages,
                                         String message,
                                         OperatorContext context) {
        List<ChatMessage> messages = new ArrayList<>();
        messages.add(SystemMessage.from(buildSystemPrompt(context)));

        ConversationState state = conversations.get(conversationKey, ignored -> new ConversationState());
        synchronized (state) {
            seedFromClientIfNeeded(state, clientMessages, message);
            for (StoredMessage storedMessage : state.messages) {
                messages.add(toLangChainMessage(storedMessage));
            }
        }

        messages.add(UserMessage.from(message));
        return ChatRequest.builder().messages(messages).build();
    }

    private void rememberExchange(ConversationKey conversationKey,
                                  List<TbOperatorChatMessage> clientMessages,
                                  String userMessage,
                                  String answer) {
        ConversationState state = conversations.get(conversationKey, ignored -> new ConversationState());
        synchronized (state) {
            seedFromClientIfNeeded(state, clientMessages, userMessage);
            appendMessage(state, new StoredMessage(TbOperatorChatMessage.Role.USER, userMessage));
            appendMessage(state, new StoredMessage(TbOperatorChatMessage.Role.ASSISTANT, answer));
        }
    }

    private void seedFromClientIfNeeded(ConversationState state, List<TbOperatorChatMessage> clientMessages, String currentMessage) {
        if (!state.messages.isEmpty() || clientMessages == null || clientMessages.isEmpty()) {
            return;
        }
        int endExclusive = clientMessages.size();
        TbOperatorChatMessage lastMessage = clientMessages.get(clientMessages.size() - 1);
        if (lastMessage != null
                && lastMessage.role() == TbOperatorChatMessage.Role.USER
                && trimMessage(lastMessage.content()).equals(currentMessage)) {
            endExclusive--;
        }
        int start = Math.max(0, endExclusive - maxHistoryMessagesFromClient);
        for (int i = start; i < endExclusive; i++) {
            TbOperatorChatMessage message = clientMessages.get(i);
            if (message == null || message.role() == null || StringUtils.isBlank(message.content())) {
                continue;
            }
            appendMessage(state, new StoredMessage(message.role(), trimMessage(message.content())));
        }
    }

    private void appendMessage(ConversationState state, StoredMessage message) {
        state.messages.addLast(message);
        while (state.messages.size() > maxConversationMessages) {
            state.messages.removeFirst();
        }
    }

    private ChatMessage toLangChainMessage(StoredMessage storedMessage) {
        return storedMessage.role == TbOperatorChatMessage.Role.ASSISTANT
                ? AiMessage.from(storedMessage.content)
                : UserMessage.from(storedMessage.content);
    }

    private String buildSystemPrompt(OperatorContext context) {
        return """
                You are a production operator assistant inside ThingsBoard Community Edition for a diesel generator dashboard.
                Use only the grounded context below.
                Never invent telemetry, alarms, causes, actions, secrets, credentials, SQL, shell commands, or admin changes.
                If data is missing, say it is unavailable.
                Keep answers concise, practical, and operator-safe.
                Do not tell the user to modify dashboards, rule chains, or platform configuration.
                If there is a critical or active alarm, call it out clearly first.
                Grounded context JSON:
                """ + context.contextJson;
    }

    private TbOperatorChatResponse toResponse(String conversationId, String answer, OperatorContext context) {
        return new TbOperatorChatResponse(
                conversationId,
                answer,
                System.currentTimeMillis(),
                context.snapshot,
                context.activeAlarms,
                SOURCES
        );
    }

    private boolean isUnsupportedQuestion(String message) {
        return UNSUPPORTED_ACTIONS.matcher(message).find();
    }

    private String unsupportedActionAnswer(String deviceName) {
        return "I can help with live " + deviceName + " operating status, alarms, AI summary, and next checks, but I cannot provide secrets or make configuration changes.";
    }

    private String fallbackAnswer(String deviceName) {
        return "The chatbot is temporarily unavailable. Please review the live " + deviceName + " telemetry and alarms on the dashboard, then retry in a moment.";
    }

    private String normalizeValue(TsKvEntry entry) {
        if (entry == null || entry.getValue() == null) {
            return "N/A";
        }
        Object value = entry.getValue();
        if (value instanceof Number number) {
            double numeric = number.doubleValue();
            if (Math.abs(numeric) >= 30000 || numeric == 32767 || numeric == -32768) {
                return "N/A";
            }
            if (numeric == Math.rint(numeric)) {
                return String.format(Locale.US, "%.0f", numeric);
            }
            return String.format(Locale.US, "%.2f", numeric);
        }
        String text = entry.getValueAsString();
        if (StringUtils.isBlank(text) || "null".equalsIgnoreCase(text)) {
            return "N/A";
        }
        return text.trim();
    }

    private String formatAlarmDetails(AlarmInfo alarm) {
        List<String> lines = new ArrayList<>();
        if (alarm.getDetails() != null) {
            String message = textFromAlarmDetails(alarm.getDetails(), "message", "summary", "description", "data");
            String action = textFromAlarmDetails(alarm.getDetails(), "recommended_action", "recommendation", "action");
            if (StringUtils.isNotBlank(message)) {
                lines.add(message);
            }
            if (StringUtils.isNotBlank(action)) {
                lines.add("Recommended action: " + action);
            }
        }
        if (lines.isEmpty()) {
            lines.add("Active alarm on " + alarm.getOriginatorName());
        }
        return String.join(" ", lines);
    }

    private String textFromAlarmDetails(com.fasterxml.jackson.databind.JsonNode details, String... fields) {
        for (String field : fields) {
            if (details.hasNonNull(field) && StringUtils.isNotBlank(details.get(field).asText())) {
                return details.get(field).asText().trim();
            }
        }
        return null;
    }

    private String trimMessage(String message) {
        String trimmed = Optional.ofNullable(message).orElse("").trim();
        if (trimmed.length() <= maxMessageChars) {
            return trimmed;
        }
        return trimmed.substring(0, maxMessageChars);
    }

    private record OperatorContext(String deviceName,
                                   String dashboardTitle,
                                   String contextJson,
                                   TbOperatorChatResponse.DeviceSnapshot snapshot,
                                   List<TbOperatorChatResponse.AlarmSummary> activeAlarms) {
    }

    private record ConversationKey(TenantId tenantId, UUID userId, UUID deviceId, String conversationId) {
    }

    private record RateLimitKey(TenantId tenantId, UUID userId, UUID deviceId) {
    }

    private record StoredMessage(TbOperatorChatMessage.Role role, String content) {
    }

    private static final class ConversationState {
        private final Deque<StoredMessage> messages = new ArrayDeque<>();
    }

    private static final class RateLimitState {
        private long windowStartedAt;
        private int requestCount;
        private long lastRequestAt;

        private RateLimitState(long windowStartedAt, int requestCount, long lastRequestAt) {
            this.windowStartedAt = windowStartedAt;
            this.requestCount = requestCount;
            this.lastRequestAt = lastRequestAt;
        }
    }

}
