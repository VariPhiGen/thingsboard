<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false pageTitle="" pageSubtitle="">
<!DOCTYPE html>
<html lang="${(locale.currentLanguageTag)!'en'}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title id="vp-page-title">${msg("loginTitle")} · Variphi</title>
  <link rel="icon" id="vp-favicon" href="${url.resourcesPath}/img/favicon.ico" />
  <#if properties.styles?has_content>
    <#list properties.styles?split(' ') as style>
      <link href="${url.resourcesPath}/${style}?v=7" rel="stylesheet" />
    </#list>
  </#if>
  <#if properties.scripts?has_content>
    <#list properties.scripts?split(' ') as script>
      <script src="${url.resourcesPath}/${script}?v=7" defer></script>
    </#list>
  </#if>
</head>
<body class="vp-body ${bodyClass}"
      data-resources-path="${url.resourcesPath}"
      data-forgot-api="${properties.forgotPasswordApiUrl!'http://localhost:4702/member/auth/forgot-password'}">
  <script>
    (function () {
      // Variphi: theme toggle removed — pin the Keycloak login to light (charcoal accent) to match Variphi IoT.
      document.body.setAttribute('data-theme', 'light');
    })();
  </script>

  <main class="vp-wrap">
    <div class="vp-card">
      <#nested "header">
      <#if pageTitle?has_content>
        <h1 class="vp-title">${pageTitle}</h1>
      </#if>
      <#if pageSubtitle?has_content>
        <p class="vp-sub">${pageSubtitle}</p>
      </#if>

      <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
        <div class="vp-alert vp-alert-${message.type}">
          <span>${kcSanitize(message.summary)?no_esc}</span>
        </div>
      </#if>

      <#nested "form">

      <#if displayInfo>
        <div class="vp-info">
          <#nested "info">
        </div>
      </#if>
    </div>
  </main>
</body>
</html>
</#macro>
