<#import "template.ftl" as layout>
<@layout.registrationLayout
    displayMessage=!messagesPerField.existsError('username','password')
    displayInfo=(realm.password && realm.registrationAllowed && !registrationDisabled??)
    pageTitle=msg("loginTitle")
    pageSubtitle=msg("loginAccountTitle"); section>
    <#if section = "header">
        <div class="vp-card-logo" aria-hidden="true">
            <img class="vp-card-logo-img" id="vp-brand-logo" src="${url.resourcesPath}/img/virtuoso-logo.png" alt="Virtuoso NetSoft"/>
        </div>
    <#elseif section = "form">
        <#if realm.password>
            <form id="kc-form-login" class="vp-form" onsubmit="login.disabled = true; return true;" action="${url.loginAction}" method="post">
                <div class="vp-field">
                    <label for="username" class="vp-label">${msg("email")}</label>
                    <input tabindex="1" id="username" class="vp-input" name="username"
                           value="${(login.username!'')}" type="email"
                           placeholder="Enter your email"
                           autofocus autocomplete="username"
                           aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>" />
                    <#if messagesPerField.existsError('username','password')>
                        <span class="vp-error" aria-live="polite">
                            ${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}
                        </span>
                    </#if>
                </div>

                <div class="vp-field">
                    <div class="vp-label-row">
                        <label for="password" class="vp-label">${msg("password")}</label>
                        <button type="button" class="vp-show-pw" data-target="password" aria-pressed="false">Show</button>
                    </div>
                    <input tabindex="2" id="password" class="vp-input" name="password"
                           type="password" placeholder="Enter your password" autocomplete="current-password"
                           aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>" />
                </div>

                <div class="vp-row">
                    <#if realm.rememberMe && !usernameHidden??>
                        <label class="vp-remember">
                            <input tabindex="3" id="rememberMe" name="rememberMe" type="checkbox"
                                   <#if login.rememberMe??>checked</#if> /> ${msg("rememberMe")}
                        </label>
                    <#else>
                        <span></span>
                    </#if>
                    <#if realm.resetPasswordAllowed>
                        <a class="vp-link" tabindex="5" href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
                    </#if>
                </div>

                <input type="hidden" id="id-hidden-input" name="credentialId"
                       <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if> />
                <input tabindex="4" class="vp-btn vp-btn-primary" name="login" id="kc-login"
                       type="submit" value="${msg("doLogIn")}" />
            </form>
        </#if>
    <#elseif section = "info">
        <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
            <span>${msg("noAccount")} <a tabindex="6" class="vp-link" href="${url.registrationUrl}">${msg("doRegister")}</a></span>
        </#if>
    </#if>
</@layout.registrationLayout>
