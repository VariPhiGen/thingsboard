(function () {
  'use strict';

  function redirectHost() {
    var params = new URLSearchParams(window.location.search);
    var redirectUri = params.get('redirect_uri') || '';
    if (!redirectUri) {
      return '';
    }
    try {
      return new URL(redirectUri).hostname.toLowerCase();
    } catch (e) {
      return '';
    }
  }

  function resourcesBase() {
    var body = document.body;
    var fromData = body && body.getAttribute('data-resources-path');
    if (fromData) {
      return fromData.replace(/\/$/, '');
    }
    var logo = document.querySelector('.vp-card-logo-img');
    if (logo && logo.src) {
      return logo.src.replace(/\/img\/[^/]+$/, '');
    }
    var icon = document.querySelector('link[rel="icon"]');
    if (icon && icon.href) {
      return icon.href.replace(/\/img\/[^/]+$/, '');
    }
    return '';
  }

  function applyVirtuosoBranding(base) {
    document.title = 'Virtuoso NetSoft';

    var favicon = document.querySelector('link[rel="icon"]');
    if (favicon) {
      favicon.href = base + '/img/virtuoso-favicon.ico';
    }

    var logo = document.querySelector('.vp-card-logo-img');
    if (logo) {
      logo.src = base + '/img/virtuoso-logo.png';
      logo.alt = 'Virtuoso NetSoft';
    }

    var title = document.querySelector('.vp-title');
    if (title) {
      title.textContent = 'Virtuoso NetSoft';
    }
  }

  function initBranding() {
    var host = redirectHost();
    if (host.indexOf('virtuosonetsoft.com') === -1) {
      return;
    }
    var base = resourcesBase();
    if (!base) {
      return;
    }
    applyVirtuosoBranding(base);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBranding);
  } else {
    initBranding();
  }
})();
