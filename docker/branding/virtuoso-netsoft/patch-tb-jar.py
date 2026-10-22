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

    /* Hide Connect mobile app, Get started widgets, and broken widget error containers */
    tb-dashboard-widget:has(.tb-error-container),
    .tb-error-container,
    tb-mobile-app-qrcode-widget,
    .tb-mobile-app-qrcode-panel,
    tb-dashboard-widget:has(tb-mobile-app-qrcode-widget),
    tb-dashboard-widget:has(.tb-mobile-app-qrcode-panel),
    tb-dashboard-widget:has([title*="Connect mobile app"]),
    tb-dashboard-widget:has([title*="Download mobile app"]),
    tb-dashboard-widget:has([title*="Get started"]),
    tb-dashboard-widget:has([title*="Getting started"]),
    tb-dashboard-widget:has([title*="Select show mobile QR code"]),
    tb-dashboard-widget:has(img[alt*="App Store"]),
    tb-dashboard-widget:has(img[alt*="Google Play"]) {
      display: none !important;
    }

    /* Hide IoT Hub from Sidebar Menu */
    .tb-site-sidenav a[href*="iot-hub"],
    .tb-site-sidenav li:has(a[href*="iot-hub"]),
    .tb-site-sidenav tb-menu-link:has(a[href*="iot-hub"]),
    .tb-side-menu li:has(a[href*="iot-hub"]),
    .tb-side-menu li:has(.is-new),
    .tb-side-menu .is-new,
    a.is-new,
    li:has(a.is-new),
    a[href*="iot-hub"],
    li:has(a[href*="iot-hub"]) {
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

    print("==> 4. Patching chunk-AWADN7CA.js (appTitle & remove IoT Hub from sidebar)")
    aw_path = f"{PUBLIC_DIR}/chunk-AWADN7CA.js"
    if os.path.exists(aw_path):
        with open(aw_path, 'r', encoding='utf-8') as f:
            js = f.read()
        changed = False
        if 'appTitle:"ThingsBoard"' in js:
            js = js.replace('appTitle:"ThingsBoard"', 'appTitle:"Virtuoso NetSoft"')
            changed = True
        if ',{id:te.iot_hub}' in js:
            js = js.replace(',{id:te.iot_hub}', '')
            changed = True
        elif '{id:te.iot_hub},' in js:
            js = js.replace('{id:te.iot_hub},', '')
            changed = True
        if changed:
            with open(aw_path, 'w', encoding='utf-8') as f:
                f.write(js)
            with open(aw_path, 'rb') as f_in, gzip.open(f"{aw_path}.gz", 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
            print("    chunk-AWADN7CA.js patched & re-gzipped (appTitle + IoT Hub removed from menu)")

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

    print("==> 7. Patching home page dashboard templates (remove broken IoT Hub & Get started, re-layout to full width)")
    import json
    
    # 7a. Tenant Admin Home Page
    dash_path = f"{PUBLIC_DIR}/assets/dashboard/tenant_admin_home_page.json"
    if os.path.exists(dash_path):
        with open(dash_path, 'r', encoding='utf-8') as f:
            d = json.load(f)

        to_remove = set()
        for wid, w in d.get('configuration', {}).get('widgets', {}).items():
            title = str(w.get('config', {}).get('title', ''))
            fqn = str(w.get('typeFullFqn', ''))
            if ('iot_hub' in fqn or 'IoT Hub' in title or 
                'getting_started' in fqn or 'Getting started' in title or 
                'Select show mobile' in title or 'mobile-app' in title or 'mobile_app' in fqn):
                to_remove.add(wid)

        for wid in to_remove:
            d['configuration']['widgets'].pop(wid, None)
            print(f"    Removed widget {wid} from tenant_admin_home_page.json")

        states = d.get('configuration', {}).get('states', {})
        if 'mobile_app_qr_code' in states:
            del states['mobile_app_qr_code']

        if 'default' in states and 'main' in states['default'].get('layouts', {}):
            main_widgets = states['default']['layouts']['main'].get('widgets', {})
            for wid in list(main_widgets.keys()):
                if wid in to_remove:
                    del main_widgets[wid]

            # Re-layout remaining 7 widgets across 120 columns seamlessly
            layout_map = {
                '35d3ac3b-f1af-dc3d-a1d1-11f351d16fc6': {'col': 0, 'row': 0, 'sizeX': 60, 'sizeY': 12},   # Devices
                '7ac20b6a-dc40-b18e-9f5f-bca20bc693bb': {'col': 60, 'row': 0, 'sizeX': 60, 'sizeY': 12},  # Alarms
                '6d6e2b1d-6ce7-4678-3745-c6b0897b2674': {'col': 0, 'row': 12, 'sizeX': 60, 'sizeY': 17},  # Dashboards
                'd70cc256-4c7b-ee06-9905-b8c5e546605f': {'col': 60, 'row': 12, 'sizeX': 60, 'sizeY': 17}, # Activity / Transport messages
                '9e3ef045-d8bc-1640-a3f4-2dd10b19d50e': {'col': 0, 'row': 29, 'sizeX': 40, 'sizeY': 14},   # Quick links
                '867f82cf-ecf2-2d5c-35cb-08c6f2edc3a4': {'col': 40, 'row': 29, 'sizeX': 40, 'sizeY': 14},  # Documentation
                'ebbd0a6e-8a47-e770-5086-7f4974250f2d': {'col': 80, 'row': 29, 'sizeX': 40, 'sizeY': 14},  # Usage info
            }
            for wid, pos in layout_map.items():
                if wid in main_widgets:
                    main_widgets[wid].update(pos)

        with open(dash_path, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        print("    tenant_admin_home_page.json cleaned and re-layouted to full 120-col width")

    # 7b. Sys Admin Home Page
    sys_path = f"{PUBLIC_DIR}/assets/dashboard/sys_admin_home_page.json"
    if os.path.exists(sys_path):
        with open(sys_path, 'r', encoding='utf-8') as f:
            d = json.load(f)

        to_remove = set()
        for wid, w in d.get('configuration', {}).get('widgets', {}).items():
            title = str(w.get('config', {}).get('title', ''))
            fqn = str(w.get('typeFullFqn', ''))
            if ('getting_started' in fqn or 'Getting started' in title or 
                'Select show mobile' in title or 'mobile-app' in title or 'mobile_app' in fqn):
                to_remove.add(wid)

        for wid in to_remove:
            d['configuration']['widgets'].pop(wid, None)
            print(f"    Removed widget {wid} from sys_admin_home_page.json")

        states = d.get('configuration', {}).get('states', {})
        if 'mobile_app_qr_code' in states:
            del states['mobile_app_qr_code']

        if 'default' in states and 'main' in states['default'].get('layouts', {}):
            main_widgets = states['default']['layouts']['main'].get('widgets', {})
            for wid in list(main_widgets.keys()):
                if wid in to_remove:
                    del main_widgets[wid]

            sys_layout_map = {
                '163025d8-3ca4-dd1e-c17b-e40d8e03e8a8': {'col': 0, 'row': 0, 'sizeX': 60, 'sizeY': 15},   # Entities info cards
                '4b5e47ed-c197-a937-d727-041ba8decec2': {'col': 60, 'row': 0, 'sizeX': 60, 'sizeY': 26},  # System info
                '867f82cf-ecf2-2d5c-35cb-08c6f2edc3a4': {'col': 0, 'row': 15, 'sizeX': 60, 'sizeY': 14},  # Documentation
                'd70cc256-4c7b-ee06-9905-b8c5e546605f': {'col': 60, 'row': 26, 'sizeX': 60, 'sizeY': 16}, # Transport messages
                'd2784f6c-0518-fd95-1d28-b21f70bdcb10': {'col': 0, 'row': 29, 'sizeX': 60, 'sizeY': 13},  # Configured features
                '66dcf1a2-9d83-6873-c693-d6a5d989b3f8': {'col': 0, 'row': 42, 'sizeX': 40, 'sizeY': 16},  # Version
                '8acbf5df-f9fc-114d-216f-86f081aa4779': {'col': 40, 'row': 42, 'sizeX': 80, 'sizeY': 16}, # Functions
            }
            for wid, pos in sys_layout_map.items():
                if wid in main_widgets:
                    main_widgets[wid].update(pos)

        with open(sys_path, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        print("    sys_admin_home_page.json cleaned and re-layouted to full 120-col width")

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
