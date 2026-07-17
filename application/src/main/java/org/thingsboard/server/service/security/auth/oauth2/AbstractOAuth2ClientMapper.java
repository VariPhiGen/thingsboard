/**
 * Copyright © 2016-2026 The Thingsboard Authors
 */
package org.thingsboard.server.service.security.auth.oauth2;

import com.fasterxml.jackson.databind.node.ObjectNode;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.thingsboard.common.util.JacksonUtil;
import org.thingsboard.server.common.data.Customer;
import org.thingsboard.server.common.data.DashboardInfo;
import org.thingsboard.server.common.data.StringUtils;
import org.thingsboard.server.common.data.Tenant;
import org.thingsboard.server.common.data.User;
import org.thingsboard.server.common.data.id.CustomerId;
import org.thingsboard.server.common.data.id.DashboardId;
import org.thingsboard.server.common.data.id.EntityId;
import org.thingsboard.server.common.data.id.IdBased;
import org.thingsboard.server.common.data.id.TenantId;
import org.thingsboard.server.common.data.oauth2.OAuth2Client;
import org.thingsboard.server.common.data.oauth2.OAuth2MapperConfig;
import org.thingsboard.server.common.data.page.PageData;
import org.thingsboard.server.common.data.page.PageLink;
import org.thingsboard.server.common.data.security.Authority;
import org.thingsboard.server.common.data.security.UserCredentials;
import org.thingsboard.server.dao.customer.CustomerService;
import org.thingsboard.server.dao.dashboard.DashboardService;
import org.thingsboard.server.dao.oauth2.OAuth2User;
import org.thingsboard.server.dao.tenant.TbTenantProfileCache;
import org.thingsboard.server.dao.tenant.TenantService;
import org.thingsboard.server.dao.user.UserService;
import org.thingsboard.server.service.entitiy.tenant.TbTenantService;
import org.thingsboard.server.service.entitiy.user.TbUserService;
import org.thingsboard.server.service.security.model.SecurityUser;
import org.thingsboard.server.service.security.model.UserPrincipal;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantLock;

@Slf4j
public abstract class AbstractOAuth2ClientMapper {

    private static final int DASHBOARDS_REQUEST_LIMIT = 10;

    @Autowired
    private UserService userService;

    @Autowired
    private BCryptPasswordEncoder passwordEncoder;

    @Autowired
    private TenantService tenantService;

    @Autowired
    private TbTenantService tbTenantService;

    @Autowired
    private CustomerService customerService;

    @Autowired
    private DashboardService dashboardService;

    @Autowired
    private TbUserService tbUserService;

    @Autowired
    protected TbTenantProfileCache tenantProfileCache;

    @Value("${edges.enabled}")
    @Getter
    private boolean edgesEnabled;

    private final Lock userCreationLock = new ReentrantLock();

    /**
     * Variphi auth-first flow: existing users always authenticate; claims required only for provisioning.
     */
    protected SecurityUser handleVariphiAuth(String email, Map<String, Object> attributes,
                                             OAuth2MapperConfig config, OAuth2Client oAuth2Client) {
        UserPrincipal principal = new UserPrincipal(UserPrincipal.Type.USER_NAME, email);
        User existing = userService.findUserByEmail(TenantId.SYS_TENANT_ID, email);
        MappingResult mapping = VariphiOAuth2MappingHelper.resolve(oAuth2Client, attributes);

        if (existing != null) {
            if (!mapping.isResolved()) {
                log.warn("Variphi SSO: claims missing for existing user {}; authenticating with current TB assignment",
                        email);
            } else {
                syncVariphiProfileBestEffort(existing, mapping.getClaims());
            }
            return toSecurityUser(existing, principal);
        }

        if (!config.isAllowUserCreation()) {
            throw new UsernameNotFoundException("User not found: " + email);
        }
        if (!mapping.isResolved()) {
            throw new OAuthProvisioningException(mapping.getUserMessage());
        }

        OAuth2User oauth2User = buildOAuth2UserProfile(email, attributes, config);
        VariphiOAuth2MappingHelper.applyClaims(oauth2User, mapping.getClaims());
        User created = provisionNewUser(oauth2User, oAuth2Client, config);
        return toSecurityUser(created, principal);
    }

    protected SecurityUser getOrCreateSecurityUserFromOAuth2User(OAuth2User oauth2User, OAuth2Client oAuth2Client) {
        OAuth2MapperConfig config = oAuth2Client.getMapperConfig();
        UserPrincipal principal = new UserPrincipal(UserPrincipal.Type.USER_NAME, oauth2User.getEmail());
        User user = userService.findUserByEmail(TenantId.SYS_TENANT_ID, oauth2User.getEmail());

        if (user == null && !config.isAllowUserCreation()) {
            throw new UsernameNotFoundException("User not found: " + oauth2User.getEmail());
        }

        if (user == null) {
            user = provisionNewUser(oauth2User, oAuth2Client, config);
        }

        return toSecurityUser(user, principal);
    }

    protected OAuth2User buildOAuth2UserProfile(String email, Map<String, Object> attributes, OAuth2MapperConfig config) {
        OAuth2User oauth2User = new OAuth2User();
        oauth2User.setEmail(email);
        if (!StringUtils.isEmpty(config.getBasic().getLastNameAttributeKey())) {
            oauth2User.setLastName(BasicMapperUtils.getStringAttributeByKey(attributes, config.getBasic().getLastNameAttributeKey()));
        }
        if (!StringUtils.isEmpty(config.getBasic().getFirstNameAttributeKey())) {
            oauth2User.setFirstName(BasicMapperUtils.getStringAttributeByKey(attributes, config.getBasic().getFirstNameAttributeKey()));
        }
        oauth2User.setAlwaysFullScreen(config.getBasic().isAlwaysFullScreen());
        if (!StringUtils.isEmpty(config.getBasic().getDefaultDashboardName())) {
            oauth2User.setDefaultDashboardName(config.getBasic().getDefaultDashboardName());
        }
        return oauth2User;
    }

    private User provisionNewUser(OAuth2User oauth2User, OAuth2Client oAuth2Client, OAuth2MapperConfig config) {
        userCreationLock.lock();
        try {
            User user = userService.findUserByEmail(TenantId.SYS_TENANT_ID, oauth2User.getEmail());
            if (user != null) {
                return user;
            }
            if (StringUtils.isEmpty(oauth2User.getTenantName())) {
                throw new OAuthProvisioningException(
                        "Tenant assignment missing from identity provider. Contact your administrator.");
            }
            user = new User();
            if (oauth2User.getCustomerId() == null && StringUtils.isEmpty(oauth2User.getCustomerName())) {
                user.setAuthority(Authority.TENANT_ADMIN);
            } else {
                user.setAuthority(Authority.CUSTOMER_USER);
            }
            TenantId tenantId = oauth2User.getTenantId() != null
                    ? oauth2User.getTenantId()
                    : getTenantId(oauth2User.getTenantName());
            user.setTenantId(tenantId);
            CustomerId customerId;
            if (user.getAuthority() == Authority.TENANT_ADMIN) {
                customerId = new CustomerId(EntityId.NULL_UUID);
            } else {
                customerId = oauth2User.getCustomerId() != null
                        ? oauth2User.getCustomerId()
                        : getCustomerId(user.getTenantId(), oauth2User.getCustomerName());
            }
            user.setCustomerId(customerId);
            user.setEmail(oauth2User.getEmail());
            user.setFirstName(oauth2User.getFirstName());
            user.setLastName(oauth2User.getLastName());

            ObjectNode additionalInfo = JacksonUtil.newObjectNode();
            if (!StringUtils.isEmpty(oauth2User.getDefaultDashboardName())) {
                Optional<DashboardId> dashboardIdOpt =
                        user.getAuthority() == Authority.TENANT_ADMIN
                                ? getDashboardId(tenantId, oauth2User.getDefaultDashboardName())
                                : getDashboardId(tenantId, customerId, oauth2User.getDefaultDashboardName());
                if (dashboardIdOpt.isPresent()) {
                    additionalInfo.put("defaultDashboardFullscreen", oauth2User.isAlwaysFullScreen());
                    additionalInfo.put("defaultDashboardId", dashboardIdOpt.get().getId().toString());
                }
            }
            if (oAuth2Client.getAdditionalInfo() != null && oAuth2Client.getAdditionalInfo().has("providerName")) {
                additionalInfo.put("authProviderName", oAuth2Client.getAdditionalInfo().get("providerName").asText());
            }
            user.setAdditionalInfo(additionalInfo);

            user = tbUserService.save(tenantId, customerId, user, false, null, null);
            if (config.isActivateUser()) {
                UserCredentials userCredentials = userService.findUserCredentialsByUserId(user.getTenantId(), user.getId());
                userService.activateUserCredentials(user.getTenantId(), userCredentials.getActivateToken(), passwordEncoder.encode(""));
            }
            return user;
        } catch (OAuthProvisioningException e) {
            throw e;
        } catch (Exception e) {
            log.error("Can't provision oauth2 user {}", oauth2User.getEmail(), e);
            throw new RuntimeException("Can't provision oauth2 user", e);
        } finally {
            userCreationLock.unlock();
        }
    }

    private void syncVariphiProfileBestEffort(User user, VariphiClaims claims) {
        if (claims == null) {
            return;
        }
        try {
            Tenant claimTenant = tenantService.findTenantByName(claims.getTenantName());
            if (claimTenant == null || !claimTenant.getId().equals(user.getTenantId())) {
                log.warn("Variphi SSO: skip sync for {} — claim tenant '{}' does not match user tenant",
                        user.getEmail(), claims.getTenantName());
                return;
            }
            TenantId tenantId = user.getTenantId();
            Authority authority = StringUtils.isEmpty(claims.getCustomerName())
                    ? Authority.TENANT_ADMIN
                    : Authority.CUSTOMER_USER;
            if (StringUtils.isEmpty(claims.getCustomerName()) && user.getAuthority() == Authority.CUSTOMER_USER) {
                log.warn("Variphi SSO: skip role sync for {} — user_type implies admin but user is CUSTOMER_USER",
                        user.getEmail());
                return;
            }
            CustomerId customerId = authority == Authority.CUSTOMER_USER
                    ? getCustomerId(tenantId, claims.getCustomerName())
                    : new CustomerId(EntityId.NULL_UUID);

            boolean changed = user.getAuthority() != authority
                    || (authority == Authority.CUSTOMER_USER && !customerId.equals(user.getCustomerId()))
                    || (authority == Authority.TENANT_ADMIN && hasAssignedCustomer(user.getCustomerId()));

            if (!changed) {
                return;
            }

            User toSave = new User(user);
            toSave.setAuthority(authority);
            toSave.setCustomerId(customerId);
            log.info("Variphi SSO: synced {} -> authority={}, customer={}",
                    user.getEmail(), authority, claims.getCustomerName());
            tbUserService.save(tenantId, customerId, toSave, false, null, null);
        } catch (Exception e) {
            log.error("Failed to sync Variphi SSO profile for {} (non-blocking)", user.getEmail(), e);
        }
    }

    private SecurityUser toSecurityUser(User user, UserPrincipal principal) {
        try {
            SecurityUser securityUser = new SecurityUser(user, true, principal);
            return (SecurityUser) new UsernamePasswordAuthenticationToken(securityUser, null, securityUser.getAuthorities()).getPrincipal();
        } catch (Exception e) {
            log.error("Can't build security user from {}", user.getEmail(), e);
            throw new RuntimeException("Can't build security user from oauth2 user", e);
        }
    }

    private static boolean hasAssignedCustomer(CustomerId customerId) {
        return customerId != null && !EntityId.NULL_UUID.equals(customerId.getId());
    }

    private TenantId getTenantId(String name) throws Exception {
        if (!TenantNameValidator.isValidTenantName(name)) {
            throw new OAuthProvisioningException(
                    "Invalid tenant assignment from identity provider. Contact your administrator.");
        }
        Tenant tenant = tenantService.findTenantByName(name);
        if (tenant != null) {
            return tenant.getId();
        }
        tenant = new Tenant();
        tenant.setTitle(name);
        tenant = tbTenantService.save(tenant);
        return tenant.getId();
    }

    private CustomerId getCustomerId(TenantId tenantId, String customerName) {
        if (StringUtils.isEmpty(customerName)) {
            return null;
        }
        Optional<Customer> customerOpt = customerService.findCustomerByTenantIdAndTitle(tenantId, customerName);
        if (customerOpt.isPresent()) {
            return customerOpt.get().getId();
        } else {
            Customer customer = new Customer();
            customer.setTenantId(tenantId);
            customer.setTitle(customerName);
            return customerService.saveCustomer(customer).getId();
        }
    }

    private Optional<DashboardId> getDashboardId(TenantId tenantId, String dashboardName) {
        return Optional.ofNullable(dashboardService.findFirstDashboardInfoByTenantIdAndName(tenantId, dashboardName)).map(IdBased::getId);
    }

    private Optional<DashboardId> getDashboardId(TenantId tenantId, CustomerId customerId, String dashboardName) {
        PageData<DashboardInfo> dashboardsPage;
        PageLink pageLink = null;
        do {
            pageLink = pageLink == null ? new PageLink(DASHBOARDS_REQUEST_LIMIT) : pageLink.nextPageLink();
            dashboardsPage = dashboardService.findDashboardsByTenantIdAndCustomerId(tenantId, customerId, pageLink);
            Optional<DashboardInfo> dashboardInfoOpt = dashboardsPage.getData().stream()
                    .filter(dashboardInfo -> dashboardName.equals(dashboardInfo.getName()))
                    .findAny();
            if (dashboardInfoOpt.isPresent()) {
                return dashboardInfoOpt.map(DashboardInfo::getId);
            }
        } while (dashboardsPage.hasNext());
        return Optional.empty();
    }
}
