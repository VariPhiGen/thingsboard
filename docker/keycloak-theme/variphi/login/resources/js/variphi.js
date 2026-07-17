(function () {
  'use strict';

  var STORAGE_KEY = 'variphi-theme';

  /* ── Theme toggle (light / dark) — cookie shares choice with launcher + ThingsBoard ── */
  function setThemeCookie(theme) {
    document.cookie = STORAGE_KEY + '=' + theme + '; path=/; max-age=31536000; SameSite=Lax';
    try { sessionStorage.setItem(STORAGE_KEY, theme); } catch (e) { /* ignore */ }
  }

  function currentTheme() {
    return document.body.getAttribute('data-theme') ||
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }

  function applyTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) { /* ignore */ }
    setThemeCookie(theme);
  }

  function initTheme() {
    // Variphi: theme toggle removed — pin to dark and share 'dark' with the launcher + ThingsBoard.
    applyTheme('light');
  }

  function toggleTheme() {
    applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
  }

  /* ── Password show / hide ── */
  function initPasswordToggles() {
    document.querySelectorAll('.vp-show-pw').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var input = document.getElementById(btn.getAttribute('data-target'));
        if (!input) return;
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.textContent = show ? 'Hide' : 'Show';
        btn.setAttribute('aria-pressed', show ? 'true' : 'false');
      });
    });
  }

  /* ── Persist theme when login form is submitted ── */
  function initLoginForm() {
    var form = document.getElementById('kc-form-login');
    if (!form) return;
    form.addEventListener('submit', function () {
      applyTheme(currentTheme());
    });
  }

  /* ── Forgot password → VGI member-service API ── */
  function initForgotPassword() {
    var form = document.getElementById('vp-forgot-form');
    if (!form) return;

    var apiUrl = document.body.getAttribute('data-forgot-api') ||
      'http://localhost:4702/member/auth/forgot-password';
    var emailEl = document.getElementById('vp-forgot-email');
    var submitBtn = document.getElementById('vp-forgot-submit');
    var errEl = document.getElementById('vp-forgot-error');
    var okEl = document.getElementById('vp-forgot-success');

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var email = (emailEl && emailEl.value || '').trim();
      if (!email) {
        if (errEl) {
          errEl.textContent = 'Please enter your email address.';
          errEl.hidden = false;
        }
        return;
      }

      if (errEl) errEl.hidden = true;
      if (okEl) okEl.hidden = true;
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Sending…';
      }

      fetch(apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json, text/plain, */*',
        },
        body: JSON.stringify({ email: email }),
      })
        .then(function (res) {
          return res.json().catch(function () { return {}; }).then(function (data) {
            if (!res.ok && !data.success) {
              throw new Error(data.message || 'Request failed');
            }
            if (okEl) okEl.hidden = false;
            if (emailEl) emailEl.disabled = true;
            if (submitBtn) submitBtn.textContent = 'Continue';
          });
        })
        .catch(function () {
          if (errEl) {
            errEl.textContent = 'Something went wrong. Please try again.';
            errEl.hidden = false;
          }
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Continue';
          }
        });
    });
  }

  function init() {
    initTheme();
    // Variphi: theme toggle disabled — dark theme only.
    // var toggle = document.getElementById('vp-theme-toggle');
    // if (toggle) toggle.addEventListener('click', toggleTheme);
    initPasswordToggles();
    initLoginForm();
    initForgotPassword();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
