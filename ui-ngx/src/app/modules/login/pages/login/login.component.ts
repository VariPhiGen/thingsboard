///
/// Copyright © 2016-2026 The Thingsboard Authors
///
/// Licensed under the Apache License, Version 2.0 (the "License");
/// you may not use this file except in compliance with the License.
/// You may obtain a copy of the License at
///
///     http://www.apache.org/licenses/LICENSE-2.0
///
/// Unless required by applicable law or agreed to in writing, software
/// distributed under the License is distributed on an "AS IS" BASIS,
/// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
/// See the License for the specific language governing permissions and
/// limitations under the License.
///

import { Component, OnInit } from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import { UntypedFormBuilder, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Constants } from '@shared/models/constants';
import { ActivatedRoute, Router } from '@angular/router';
import { OAuth2ClientLoginInfo } from '@shared/models/oauth2.models';
import { validateEmail } from '@app/core/utils';
import { PageComponent } from '@shared/components/page.component';
import { finalize } from 'rxjs/operators';

@Component({
    selector: 'tb-login',
    templateUrl: './login.component.html',
    styleUrls: ['./login.component.scss'],
    standalone: false
})
export class LoginComponent extends PageComponent implements OnInit {

  passwordViolation = false;
  isLoading = false;

  loginFormGroup = this.fb.group({
    username: ['', [Validators.required, validateEmail]],
    password: ['']
  });
  oauth2Clients: Array<OAuth2ClientLoginInfo> = null;
  autoRedirecting = false;
  // Show a neutral spinner (never the form) until we know whether to auto-redirect to SSO.
  // This prevents the native login form from flashing before the Keycloak redirect.
  checking = true;
  // What to render once resolved.
  showSsoButtons = false;
  showLocalForm = false;
  private readonly ssoRecoveryAttemptKey = 'tb_sso_recovery_attempted';

  constructor(private authService: AuthService,
              public fb: UntypedFormBuilder,
              private route: ActivatedRoute,
              private router: Router) {
    super();
  }

  ngOnInit() {
    // Keycloak SSO is the only visible login UI: /login opens Keycloak directly.
    // The native email/password form is reachable ONLY via the unadvertised
    // /login?localLogin=true (emergency access for sysadmin@thingsboard.org).
    const qp = this.route.snapshot.queryParamMap;
    const localLogin = qp.get('localLogin') === 'true';

    // An OAuth2 result is already in flight: the app is consuming the success token, or an error
    // is being shown. NEVER start a new SSO flow here — doing so spawns a second authorization
    // request whose cookie is gone, failing with [authorization_request_not_found].
    if (qp.get('accessToken') || qp.get('publicId')) {
      this.checking = true; // show the spinner while the app logs in; no redirect
      return;
    }
    const loginError = decodeURIComponent(qp.get('loginError') || '');
    const authRequestNotFound = /authorization_request_not_found/i.test(loginError);
    const provisioningError = /tenant assignment|not provisioned|identity provider/i.test(loginError);
    const afterError = !!qp.get('loginError') || provisioningError;

    const decide = (clients: Array<OAuth2ClientLoginInfo>) => {
      this.oauth2Clients = clients;
      const hasClients = !!clients?.length;
      if (authRequestNotFound && hasClients) {
        // Recover stale OAuth2 state by performing a single silent retry to SSO.
        const alreadyRetried = sessionStorage.getItem(this.ssoRecoveryAttemptKey) === 'true';
        if (!alreadyRetried) {
          sessionStorage.setItem(this.ssoRecoveryAttemptKey, 'true');
          this.autoRedirecting = true;
          this.checking = true;
          this.router.navigate([], {
            relativeTo: this.route,
            queryParams: {loginError: null},
            queryParamsHandling: 'merge',
            replaceUrl: true
          });
          setTimeout(() => {
            window.location.href = this.getOAuth2Uri(clients[0]);
          });
          return;
        }
        sessionStorage.removeItem(this.ssoRecoveryAttemptKey);
        this.router.navigate([], {
          relativeTo: this.route,
          queryParams: {loginError: null},
          queryParamsHandling: 'merge',
          replaceUrl: true
        });
      }
      if (localLogin) {
        this.showLocalForm = true;
        this.showSsoButtons = hasClients;
        this.checking = false;
        return;
      }
      if (!hasClients) {
        // SSO is required; keep spinner until OAuth2 clients are available (or user uses ?localLogin=true).
        this.checking = true;
        this.autoRedirecting = false;
        return;
      }
      if (clients.length === 1 && !afterError) {
        // Single Keycloak client — go straight to it (no intermediate screen).
        sessionStorage.removeItem(this.ssoRecoveryAttemptKey);
        this.autoRedirecting = true;
        setTimeout(() => {
          window.location.href = this.getOAuth2Uri(clients[0]);
        });
      } else {
        // After an SSO error (retry) or with multiple providers: show the button(s), don't auto-loop.
        if (!authRequestNotFound) {
          sessionStorage.removeItem(this.ssoRecoveryAttemptKey);
        }
        this.showSsoButtons = true;
        this.checking = false;
      }
    };

    const existing = this.authService.oauth2Clients;
    if (existing != null) {
      decide(existing);
    } else {
      this.authService.loadOAuth2Clients().subscribe({
        next: decide,
        error: () => decide([])
      });
    }
  }

  login(): void {
    if (this.loginFormGroup.valid) {
      this.isLoading = true;
      this.authService.login(this.loginFormGroup.value).pipe(
        finalize(() => {this.isLoading = false;})
      ).subscribe({
        error: (error: HttpErrorResponse) => {
          if (error && error.error && error.error.errorCode) {
            if (error.error.errorCode === Constants.serverErrorCode.credentialsExpired) {
              this.router.navigateByUrl(`login/resetExpiredPassword?resetToken=${error.error.resetToken}`);
            } else if (error.error.errorCode === Constants.serverErrorCode.passwordViolation) {
              this.passwordViolation = true;
            }
          }
        }
      });
    } else {
      this.loginFormGroup.markAllAsTouched();
    }
  }

  getOAuth2Uri(oauth2Client: OAuth2ClientLoginInfo): string {
    let result = "";
    if (this.authService.redirectUrl) {
      result += "?prevUri=" + encodeURIComponent(this.authService.redirectUrl);
    }
    return oauth2Client.url + result;
  }

}
