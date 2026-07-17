<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title></title>
  <script>
    (function () {
      var KEY = 'variphi-theme';
      var t = 'dark';
      try {
        var m = document.cookie.match(new RegExp('(?:^|;\\s*)' + KEY + '=(light|dark)'));
        if (m) t = m[1];
        else {
          var s = localStorage.getItem(KEY);
          if (s === 'light' || s === 'dark') t = s;
        }
      } catch (e) { /* ignore */ }
      var dark = t === 'dark';
      var bg = dark ? '#0c1018' : '#f3f4f6';
      var track = dark ? 'rgba(255,255,255,.1)' : 'rgba(0,0,0,.08)';
      var head = dark ? '#e5e7eb' : '#009661';
      document.documentElement.setAttribute('data-vp-theme', t);
      document.write(
        '<style>' +
        'html,body{margin:0;height:100%;background:' + bg + '}' +
        'body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px}' +
        'img{height:42px;width:auto;opacity:.95}' +
        '.vp-spin{width:32px;height:32px;border:2px solid ' + track + ';' +
        'border-top-color:' + head + ';border-radius:50%;animation:vpSpin .7s linear infinite}' +
        '@keyframes vpSpin{to{transform:rotate(360deg)}}</style>'
      );
      window.__vpLogoutTheme = t;
    })();
  </script>
</head>
<body>
  <img id="vp-logout-logo" src="${url.resourcesPath}/img/variphi-logo.png" alt="Variphi" />
  <div class="vp-spin" role="status" aria-label="Loading"></div>
  <form id="kc-logout-confirm" action="${url.logoutConfirmAction}" method="POST" hidden>
    <input type="hidden" name="session_code" value="${logoutConfirm.code}">
    <input type="hidden" name="confirmLogout" value="true"/>
  </form>
  <script>
    (function () {
      var params = new URLSearchParams(window.location.search);
      var uri = params.get('redirect_uri') || params.get('post_logout_redirect_uri') || '';
      var isVirtuoso = false;
      try {
        isVirtuoso = uri && new URL(uri).hostname.toLowerCase().indexOf('virtuosonetsoft.com') !== -1;
      } catch (e) { /* ignore */ }
      var img = document.getElementById('vp-logout-logo');
      if (isVirtuoso) {
        document.title = 'Virtuoso NetSoft';
        if (img) {
          img.src = '${url.resourcesPath}/img/virtuoso-logo.png';
          img.alt = 'Virtuoso NetSoft';
        }
      } else if (window.__vpLogoutTheme === 'light' && img) {
        img.src = img.src.replace('variphi-logo.png', 'variphi-logo-dark-text.png');
      }
      setTimeout(function () {
        document.getElementById('kc-logout-confirm').submit();
      }, 120);
    })();
  </script>
</body>
</html>
