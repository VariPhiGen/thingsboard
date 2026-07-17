<#import "template.ftl" as layout>
<@layout.registrationLayout
    displayMessage=false
    pageTitle=msg("resetPasswordTitle")
    pageSubtitle=msg("emailInstruction"); section>
    <#if section = "header">
    <#elseif section = "form">
        <form id="vp-forgot-form" class="vp-form" novalidate>
            <div class="vp-field">
                <label for="vp-forgot-email" class="vp-label">${msg("emailForgotTitle")}</label>
                <input tabindex="1" id="vp-forgot-email" class="vp-input" name="email" type="email"
                       placeholder="Enter your email" autocomplete="email" required />
                <span class="vp-error" id="vp-forgot-error" hidden aria-live="polite"></span>
            </div>

            <div class="vp-alert vp-alert-success" id="vp-forgot-success" hidden aria-live="polite">
                If your email exists, a password reset link has been sent. Please check your inbox.
            </div>

            <button tabindex="2" class="vp-btn vp-btn-primary" id="vp-forgot-submit" type="submit">
                ${msg("doSubmit")}
            </button>
        </form>

        <p class="vp-back">
            <a class="vp-link" href="${url.loginUrl}">${msg("backToLogin")}</a>
        </p>
    </#if>
</@layout.registrationLayout>
