<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Virtuoso NetSoft</title>
  <script>
    (function () {
      var bg = '#f3f4f6';
      var track = 'rgba(0,0,0,.08)';
      var head = '#009661';
      document.documentElement.setAttribute('data-vp-theme', 'light');
      document.write(
        '<style>' +
        'html,body{margin:0;height:100%;background:' + bg + '}' +
        'body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px}' +
        'img{height:42px;width:auto;opacity:.95}' +
        '.vp-spin{width:32px;height:32px;border:2px solid ' + track + ';' +
        'border-top-color:' + head + ';border-radius:50%;animation:vpSpin .7s linear infinite}' +
        '@keyframes vpSpin{to{transform:rotate(360deg)}}</style>'
      );
    })();
  </script>
</head>
<body>
  <img id="vp-logout-logo" src="${url.resourcesPath}/img/virtuoso-logo.png" alt="Virtuoso NetSoft" />
  <div class="vp-spin" role="status" aria-label="Loading"></div>
  <form id="kc-logout-confirm" action="${url.logoutConfirmAction}" method="POST" hidden>
    <input type="hidden" name="session_code" value="${logoutConfirm.code}">
    <input type="hidden" name="confirmLogout" value="true"/>
  </form>
  <script>
    setTimeout(function () {
      document.getElementById('kc-logout-confirm').submit();
    }, 120);
  </script>
</body>
</html>
