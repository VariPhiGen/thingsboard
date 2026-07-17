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
package org.thingsboard.server.service.security.oauth2;

import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.thingsboard.common.util.JacksonUtil;
import org.thingsboard.server.common.data.EntityType;
import org.thingsboard.server.common.data.Tenant;
import org.thingsboard.server.common.data.id.TenantId;
import org.thingsboard.server.common.data.page.PageData;
import org.thingsboard.server.common.data.page.PageLink;
import org.thingsboard.server.common.data.rule.NodeConnectionInfo;
import org.thingsboard.server.common.data.rule.RuleChain;
import org.thingsboard.server.common.data.rule.RuleChainMetaData;
import org.thingsboard.server.common.data.rule.RuleNode;
import org.thingsboard.server.dao.rule.RuleChainService;
import org.thingsboard.server.dao.tenant.TenantService;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;

@Service
@RequiredArgsConstructor
@Slf4j
public class VariphiRuleChainSeederService {

    static final String MARKER_NODE_NAME = "Variphi Viewer Entity Type Switch";
    static final String ASSIGN_DASHBOARD_NODE_NAME = "Variphi Assign Dashboard to Public";
    static final String ASSIGN_DEVICE_NODE_NAME = "Variphi Assign Device to Public";
    static final String MESSAGE_TYPE_SWITCH_NODE_NAME = "Message Type Switch";
    static final String ENTITY_CREATED_CONNECTION = "Entity Created";

    private static final String ORIGINATOR_TYPE_SWITCH = "org.thingsboard.rule.engine.filter.TbOriginatorTypeSwitchNode";
    private static final String ASSIGN_TO_CUSTOMER = "org.thingsboard.rule.engine.action.TbAssignToCustomerNode";

    private final TenantService tenantService;
    private final RuleChainService ruleChainService;

    @Value("${security.oauth2.keycloak.enabled:false}")
    private boolean keycloakSsoEnabled;

    @Value("${security.oauth2.keycloak.viewer-customer-name:Public}")
    private String viewerCustomerName;

    public void seedViewerAutoAssignRuleChain() {
        if (!keycloakSsoEnabled) {
            return;
        }

        PageLink pageLink = new PageLink(100);
        PageData<Tenant> tenants;
        do {
            tenants = tenantService.findTenants(pageLink);
            for (Tenant tenant : tenants.getData()) {
                try {
                    patchTenantRootRuleChainIfNeeded(tenant.getId());
                } catch (Exception e) {
                    log.error("Failed to patch Variphi viewer auto-assign rule chain for tenant [{}]", tenant.getTitle(), e);
                }
            }
            pageLink = pageLink.nextPageLink();
        } while (tenants.hasNext());
    }

    private void patchTenantRootRuleChainIfNeeded(TenantId tenantId) {
        RuleChain rootRuleChain = ruleChainService.getRootTenantRuleChain(tenantId);
        if (rootRuleChain == null) {
            log.debug("Tenant [{}] has no root rule chain; skipping Variphi viewer auto-assign patch.", tenantId);
            return;
        }

        RuleChainMetaData metaData = ruleChainService.loadRuleChainMetaData(tenantId, rootRuleChain.getId());
        if (metaData == null || metaData.getNodes() == null) {
            return;
        }

        if (metaData.getNodes().stream().anyMatch(node -> MARKER_NODE_NAME.equals(node.getName()))) {
            log.debug("Variphi viewer auto-assign rule chain already present for tenant [{}].", tenantId);
            return;
        }

        int messageTypeSwitchIndex = findNodeIndex(metaData.getNodes(), MESSAGE_TYPE_SWITCH_NODE_NAME);
        if (messageTypeSwitchIndex < 0) {
            log.warn("Root rule chain for tenant [{}] has no '{}' node; skipping Variphi patch.", tenantId, MESSAGE_TYPE_SWITCH_NODE_NAME);
            return;
        }

        List<RuleNode> nodes = new ArrayList<>(metaData.getNodes());
        int entityTypeSwitchIndex = nodes.size();
        nodes.add(createEntityTypeSwitchNode());
        int assignDashboardIndex = nodes.size();
        nodes.add(createAssignToCustomerNode(ASSIGN_DASHBOARD_NODE_NAME, 220));
        int assignDeviceIndex = nodes.size();
        nodes.add(createAssignToCustomerNode(ASSIGN_DEVICE_NODE_NAME, 340));

        List<NodeConnectionInfo> connections = metaData.getConnections() != null
                ? new ArrayList<>(metaData.getConnections())
                : new ArrayList<>();
        connections.add(connection(messageTypeSwitchIndex, entityTypeSwitchIndex, ENTITY_CREATED_CONNECTION));
        connections.add(connection(entityTypeSwitchIndex, assignDashboardIndex, EntityType.DASHBOARD.getNormalName()));
        connections.add(connection(entityTypeSwitchIndex, assignDeviceIndex, EntityType.DEVICE.getNormalName()));

        RuleChainMetaData updated = new RuleChainMetaData();
        updated.setRuleChainId(rootRuleChain.getId());
        updated.setVersion(metaData.getVersion());
        updated.setFirstNodeIndex(metaData.getFirstNodeIndex());
        updated.setNodes(nodes);
        updated.setConnections(connections);
        updated.setRuleChainConnections(metaData.getRuleChainConnections());
        updated.setNotes(metaData.getNotes());

        ruleChainService.saveRuleChainMetaData(tenantId, updated, Function.identity());
        log.info("Patched root rule chain for tenant [{}]: auto-assign new dashboards/devices to customer '{}'.",
                tenantId, viewerCustomerName);
    }

    private static int findNodeIndex(List<RuleNode> nodes, String name) {
        for (int i = 0; i < nodes.size(); i++) {
            if (name.equals(nodes.get(i).getName())) {
                return i;
            }
        }
        return -1;
    }

    private RuleNode createEntityTypeSwitchNode() {
        RuleNode node = new RuleNode();
        node.setType(ORIGINATOR_TYPE_SWITCH);
        node.setName(MARKER_NODE_NAME);
        node.setConfigurationVersion(0);
        node.setConfiguration(JacksonUtil.toJsonNode("{\"version\":0}"));
        ObjectNode layout = JacksonUtil.newObjectNode();
        layout.put("layoutX", 520);
        layout.put("layoutY", 280);
        node.setAdditionalInfo(layout);
        return node;
    }

    private RuleNode createAssignToCustomerNode(String name, int layoutY) {
        RuleNode node = new RuleNode();
        node.setType(ASSIGN_TO_CUSTOMER);
        node.setName(name);
        node.setConfigurationVersion(1);
        ObjectNode configuration = JacksonUtil.newObjectNode();
        configuration.put("customerNamePattern", viewerCustomerName);
        configuration.put("createCustomerIfNotExists", false);
        node.setConfiguration(configuration);
        ObjectNode layout = JacksonUtil.newObjectNode();
        layout.put("layoutX", 760);
        layout.put("layoutY", layoutY);
        node.setAdditionalInfo(layout);
        return node;
    }

    private static NodeConnectionInfo connection(int fromIndex, int toIndex, String type) {
        NodeConnectionInfo connection = new NodeConnectionInfo();
        connection.setFromIndex(fromIndex);
        connection.setToIndex(toIndex);
        connection.setType(type);
        return connection;
    }
}
