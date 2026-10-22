#!/usr/bin/env python3
"""
Patch ThingsBoard ui-ngx jar with:
1. Virtuoso NetSoft branding assets (logos, favicons)
2. Dark Charcoal Theme (#2B2F3A / #1F232C) for navbar, sidebar, buttons
3. Auto-redirect on /login directly to Keycloak SSO
4. Title and 'Powered by Virtuoso NetSoft v.4.3.1.6' text
"""
import os
import shutil
import gzip
import zipfile
import io

EXTRACT_DIR = '/tmp/tb_extract'
PUBLIC_DIR = '/tmp/tb_extract/ui/public'
BRANDING_DIR = '/home/ubuntu/thingsboard/docker/branding/virtuoso-netsoft'

DARK_CHARCOAL_CSS = """
    /* Virtuoso NetSoft Dark Charcoal Theme (#2B2F3A / #1F232C) */
    .mat-toolbar.mat-primary,
    .tb-primary-toolbar,
    .mat-mdc-toolbar.mat-primary,
    mat-toolbar[color="primary"] {
      background-color: #2B2F3A !important;
      color: #ffffff !important;
    }

    mat-sidenav.tb-site-sidenav,
    .tb-site-sidenav,
    .tb-side-menu-toolbar,
    .tb-nav-header {
      background-color: #1F232C !important;
    }

    .tb-nav-header-toolbar,
    .tb-nav-logo {
      background-color: #2B2F3A !important;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
      width: 100% !important;
      justify-content: flex-start !important;
      padding-left: 8px !important;
      box-sizing: border-box !important;
    }

    .tb-site-sidenav .mat-mdc-list-item,
    .tb-site-sidenav .mat-nav-list .mat-list-item,
    .tb-site-sidenav .tb-side-menu-toolbar .mat-mdc-list-item {
      color: #CBD5E1 !important;
    }

    .tb-site-sidenav .mat-mdc-list-item:hover,
    .tb-site-sidenav .mat-nav-list .mat-list-item:hover {
      background-color: rgba(255, 255, 255, 0.06) !important;
    }

    .tb-site-sidenav .mat-mdc-list-item.tb-active,
    .tb-site-sidenav .mat-nav-list .mat-list-item.tb-active,
    .tb-site-sidenav .mat-mdc-list-item.active,
    .tb-site-sidenav .tb-active {
      background-color: #2B2F3A !important;
      color: #ffffff !important;
    }

    .tb-primary-toolbar button.mat-mdc-icon-button,
    .tb-primary-toolbar button.mat-mdc-icon-button .mat-icon,
    .tb-primary-toolbar .mat-icon,
    .tb-primary-toolbar .tb-user-display-name,
    .tb-primary-toolbar .tb-user-authority {
      color: #ffffff !important;
    }

    .tb-logo-title, .login-logo {
      width: 152px !important;
      height: 56px !important;
      display: block !important;
      flex-shrink: 0 !important;
    }
    .tb-logo-title img, .login-logo img {
      width: 100% !important;
      height: 100% !important;
      object-fit: contain !important;
    }
    .tb-powered-by-footer span a {
      pointer-events: auto !important;
    }
    tb-github-badge {
      display: none !important;
    }

    /* Hide Connect mobile app widget completely */
    tb-mobile-app-qrcode-widget,
    .tb-mobile-app-qrcode-panel,
    tb-dashboard-widget:has(tb-mobile-app-qrcode-widget),
    tb-dashboard-widget:has(.tb-mobile-app-qrcode-panel),
    tb-dashboard-widget:has([title*="Connect mobile app"]),
    tb-dashboard-widget:has([title*="Download mobile app"]),
    tb-dashboard-widget:has(img[alt*="App Store"]),
    tb-dashboard-widget:has(img[alt*="Google Play"]) {
      display: none !important;
    }
"""

SSO_REDIRECT_JS = """
  <script>
    (function() {
      var isLoggingOut = false;

      function doKeycloakLogout() {
        try {
          localStorage.clear();
          sessionStorage.clear();
          var f = document.createElement("form");
          f.method = "POST";
          f.action = "https://auth.virtuosonetsoft.variphi.com/realms/viot/protocol/openid-connect/logout";
          var c = document.createElement("input"); c.type = "hidden"; c.name = "client_id"; c.value = "viot"; f.appendChild(c);
          var r = document.createElement("input"); r.type = "hidden"; r.name = "post_logout_redirect_uri"; r.value = window.location.origin + "/login"; f.appendChild(r);
          document.body.appendChild(f);
          f.submit();
        } catch(e) {
          console.error("SSO logout error", e);
        }
      }

      window.triggerKeycloakLogout = doKeycloakLogout;

      // Listen for click on logout menu item / button
      document.addEventListener("click", function(e) {
        var el = e.target && e.target.closest ? e.target.closest("button, a, mat-list-item, [role='menuitem']") : null;
        if (el) {
          var txt = (el.innerText || "").trim().toLowerCase();
          if (txt.includes("log out") || txt.includes("logout")) {
            isLoggingOut = true;
          }
        }
      }, true);

      // Intercept XHR to /api/auth/logout
      var origOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function(method, url) {
        if (url && (url === "/api/auth/logout" || (typeof url === "string" && url.indexOf("/api/auth/logout") !== -1))) {
          isLoggingOut = true;
          this.addEventListener("loadend", function() {
            setTimeout(doKeycloakLogout, 50);
          });
        }
        return origOpen.apply(this, arguments);
      };

      function checkLogin() {
        if (isLoggingOut) {
          doKeycloakLogout();
          return;
        }
        if (window.location.pathname === '/login' && 
            !window.location.search.includes('localLogin=true') && 
            !window.location.search.includes('accessToken') && 
            !window.location.search.includes('loginError')) {
          window.location.replace('/oauth2/authorization/68b2bc20-5e98-11f1-bade-0bee8153e08f');
        }
      }

      checkLogin();
      window.addEventListener('popstate', checkLogin);
      var lastPath = location.pathname;
      var obs = new MutationObserver(function() {
        if (location.pathname !== lastPath) {
          lastPath = location.pathname;
          checkLogin();
        }
      });
      obs.observe(document, {subtree: true, childList: true});
    })();
  </script>
"""

def main():
    print("==> 1. Copying Virtuoso branding assets")
    shutil.copy2(f"{BRANDING_DIR}/assets/logo_title_white.svg", f"{PUBLIC_DIR}/assets/logo_title_white.svg")
    shutil.copy2(f"{BRANDING_DIR}/assets/logo_white.svg", f"{PUBLIC_DIR}/assets/logo_white.svg")
    shutil.copy2(f"{BRANDING_DIR}/assets/virtuoso-favicon.png", f"{PUBLIC_DIR}/assets/virtuoso-favicon.png")
    shutil.copy2(f"{BRANDING_DIR}/assets/virtuoso-logo.png", f"{PUBLIC_DIR}/assets/virtuoso-logo.png")
    shutil.copy2(f"{BRANDING_DIR}/assets/virtuoso-favicon.ico", f"{PUBLIC_DIR}/thingsboard.ico")

    print("==> 2. Patching index.html")
    index_path = f"{PUBLIC_DIR}/index.html"
    with open(index_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # Title
    html = html.replace("<title>ThingsBoard</title>", "<title>Virtuoso NetSoft</title>")

    # Clean and inject updated theme styles
    import re
    html = re.sub(r'<style type="text/css">\s*/\* Virtuoso NetSoft Dark Charcoal Theme.*?</style>\s*', '', html, flags=re.DOTALL)
    html = html.replace("</head>", f"<style type=\"text/css\">{DARK_CHARCOAL_CSS}</style>\n</head>")

    # Clean previous SSO scripts and inject updated SSO_REDIRECT_JS with logout handler
    html = re.sub(r'<script>\s*\(function\(\)\s*\{\s*(var isLoggingOut|function checkLogin).*?</script>\s*', '', html, flags=re.DOTALL)
    html = html.replace("</body>", f"{SSO_REDIRECT_JS.strip()}\n</body>")

    if 'virtuoso-favicon.png' not in html:
        html = html.replace('<link rel="icon" type="image/x-icon" href="thingsboard.ico">',
                            '<link rel="icon" type="image/x-icon" href="thingsboard.ico">\n  <link rel="icon" type="image/png" href="assets/virtuoso-favicon.png">')

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print("    index.html patched with Dark Charcoal Theme, Connect mobile app hide, and SSO logout/auto-redirect")

    print("==> 3. Patching styles-WUQVJSVC.css")
    css_path = f"{PUBLIC_DIR}/styles-WUQVJSVC.css"
    if os.path.exists(css_path):
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()
        css = re.sub(r'/\* Virtuoso NetSoft Dark Charcoal Theme.*', '', css, flags=re.DOTALL)
        css += f"\n{DARK_CHARCOAL_CSS}\n"
        with open(css_path, 'w', encoding='utf-8') as f:
            f.write(css)
        print("    styles-WUQVJSVC.css updated with Dark Charcoal theme and mobile app hide overrides")

    print("==> 4. Patching chunk-AWADN7CA.js (appTitle)")
    aw_path = f"{PUBLIC_DIR}/chunk-AWADN7CA.js"
    if os.path.exists(aw_path):
        with open(aw_path, 'r', encoding='utf-8') as f:
            js = f.read()
        if 'appTitle:"ThingsBoard"' in js:
            js = js.replace('appTitle:"ThingsBoard"', 'appTitle:"Virtuoso NetSoft"')
            with open(aw_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(aw_path, 'rb') as f_in, gzip.open(f"{aw_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    chunk-AWADN7CA.js patched & re-gzipped")

    print("==> 5. Patching chunk-QBQ4XMPH.js (Powered by & links)")
    qb_path = f"{PUBLIC_DIR}/chunk-QBQ4XMPH.js"
    if os.path.exists(qb_path):
        with open(qb_path, 'r', encoding='utf-8') as f:
            js = f.read()
        changed = False
        if 'ThingsBoard v.' in js:
            js = js.replace('ThingsBoard v.', 'Virtuoso NetSoft v.')
            changed = True
        if '["href","https://thingsboard.io","target","_blank"]' in js:
            js = js.replace('["href","https://thingsboard.io","target","_blank"]', '["href","https://virtuosonetsoft.com","target","_blank"]')
            changed = True
        if changed:
            with open(qb_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(qb_path, 'rb') as f_in, gzip.open(f"{qb_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    chunk-QBQ4XMPH.js patched & re-gzipped")

    print("==> 6. Patching main-RUDBBS27.js (login logo link & title)")
    main_path = f"{PUBLIC_DIR}/main-RUDBBS27.js"
    if os.path.exists(main_path):
        with open(main_path, 'r', encoding='utf-8') as f:
            js = f.read()
        changed = False
        if '["link","https://thingsboard.io","target","_blank",1,"login-logo"]' in js:
            js = js.replace('["link","https://thingsboard.io","target","_blank",1,"login-logo"]', '["link","https://virtuosonetsoft.com","target","_blank",1,"login-logo"]')
            changed = True
        if 'console.log(`ThingsBoard Version:' in js:
            js = js.replace('console.log(`ThingsBoard Version:', 'console.log(`Virtuoso NetSoft Version:')
            changed = True
        if changed:
            with open(main_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(main_path, 'rb') as f_in, gzip.open(f"{main_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    main-RUDBBS27.js patched & re-gzipped")

    print("==> 7. Patching home page dashboard templates to remove Connect mobile app")
    import json
    for dash_file in ["tenant_admin_home_page.json", "sys_admin_home_page.json"]:
        dash_path = f"{PUBLIC_DIR}/assets/dashboard/{dash_file}"
        if os.path.exists(dash_path):
            with open(dash_path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            
            # Remove mobile_app_qr_code widget if present
            removed_ids = set()
            for wid, w in list(d.get('configuration', {}).get('widgets', {}).items()):
                if w.get('typeFullFqn') == 'system.mobile_app_qr_code' or 'mobile-app' in str(w.get('config', {}).get('title')):
                    del d['configuration']['widgets'][wid]
                    removed_ids.add(wid)
                    print(f"    Removed widget {wid} from {dash_file}")

            # Remove from states -> mobile_app_qr_code -> layouts -> main -> widgets
            states = d.get('configuration', {}).get('states', {})
            if 'mobile_app_qr_code' in states:
                mwidgets = states['mobile_app_qr_code'].get('layouts', {}).get('main', {}).get('widgets', {})
                for wid in list(mwidgets.keys()):
                    if wid in removed_ids or wid not in d.get('configuration', {}).get('widgets', {}):
                        del mwidgets[wid]
                        print(f"    Removed {wid} from mobile_app_qr_code layout in {dash_file}")
                for wid in mwidgets.keys():
                    mwidgets[wid]['sizeY'] = 58
                    mwidgets[wid]['mobileHide'] = False
                    print(f"    Set widget {wid} sizeY to 58 in mobile_app_qr_code layout in {dash_file}")

            # In select show mobile QR code widget, render state mobile_app_qr_code (which now contains only Getting Started)
            for wid, w in d.get('configuration', {}).get('widgets', {}).items():
                if w.get('config', {}).get('title') == 'Select show mobile QR code':
                    w['config']['settings']['markdownTextFunction'] = (
                        "let html = '<div style=\"width: 100%; height: 100%;\">';\n"
                        "let supportMobile = '${mobileQrEnabled:valuePlaceholder}';\n"
                        "ctx.dashboardWidget.widgetLayout.mobileHide = false;\n"
                        "html += '<tb-dashboard-state stateId=\"mobile_app_qr_code\" [ctx]=\"ctx\"></tb-dashboard-state>';\n"
                        "html += '</div>';\n"
                        "return html;"
                    )
                    print(f"    Updated markdownTextFunction in widget {wid} in {dash_file}")

            with open(dash_path, 'w', encoding='utf-8') as f:
                json.dump(d, f)
            print(f"    {dash_file} patched and saved")

    print("==> 8. Patching chunk-3WMNFA25.js (Keycloak SSO Logout)")
    chunk_path = f"{PUBLIC_DIR}/chunk-3WMNFA25.js"
    if os.path.exists(chunk_path):
        with open(chunk_path, 'r', encoding='utf-8') as f:
            js = f.read()
        target = 'logout(i=!1,n=!1){i&&(this.redirectUrl=this.router.url),n?this.clearJwtToken():this.http.post("/api/auth/logout",null,vt(!0,!0)).subscribe(()=>{this.clearJwtToken()},()=>{this.clearJwtToken()})}'
        replacement = 'logout(i=!1,n=!1){i&&(this.redirectUrl=this.router.url);try{if(window.triggerKeycloakLogout){this.clearJwtToken();window.triggerKeycloakLogout();return;}var _f=document.createElement("form");_f.method="POST";_f.action="https://auth.virtuosonetsoft.variphi.com/realms/viot/protocol/openid-connect/logout";var _c=document.createElement("input");_c.type="hidden";_c.name="client_id";_c.value="viot";_f.appendChild(_c);var _r=document.createElement("input");_r.type="hidden";_r.name="post_logout_redirect_uri";_r.value=window.location.origin+"/login";_f.appendChild(_r);document.body.appendChild(_f);this.clearJwtToken();_f.submit();return;}catch(e){}n?this.clearJwtToken():this.http.post("/api/auth/logout",null,vt(!0,!0)).subscribe(()=>{this.clearJwtToken()},()=>{this.clearJwtToken()})}'
        if target in js:
            js = js.replace(target, replacement)
            with open(chunk_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(chunk_path, 'rb') as f_in, gzip.open(f"{chunk_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    chunk-3WMNFA25.js patched with Keycloak SSO logout & re-gzipped")
        elif 'triggerKeycloakLogout' in js:
            print("    chunk-3WMNFA25.js already patched with Keycloak SSO logout")
        else:
            print("    WARNING: target logout signature not found in chunk-3WMNFA25.js")

    print("==> DONE patching public UI files")

if __name__ == '__main__':
    main()
