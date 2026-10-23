#!/usr/bin/env python3
"""
Patch ThingsBoard backend email templates and messages.properties with:
1. Virtuoso NetSoft branding (Dark Charcoal header, teal accent, corporate layout)
2. Complete removal of all ThingsBoard references, text, links, and copyright
3. Updating i18n/messages.properties email subjects to Virtuoso NetSoft
"""
import os
import zipfile
import shutil
import time

TEMPLATES_DIR = '/tmp/tb_patch_classes/BOOT-INF/classes/templates'
I18N_DIR = '/tmp/tb_patch_classes/BOOT-INF/classes/i18n'
TB_JAR = '/tmp/tb.jar'

def get_email_wrapper(title, content):
    return f"""<#--
    SPDX-FileCopyrightText: Copyright The Virtuoso NetSoft Authors
    SPDX-License-Identifier: Apache-2.0
-->
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; box-sizing: border-box; font-size: 14px; margin: 0;">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<title>{title}</title>
<style type="text/css">
body {{
  margin: 0;
  padding: 0;
  background-color: #F1F5F9;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -webkit-text-size-adjust: none;
  width: 100% !important;
  height: 100%;
  line-height: 1.6em;
}}
@media only screen and (max-width: 620px) {{
  .email-container {{
    width: 100% !important;
    padding: 10px !important;
  }}
  .card-body {{
    padding: 24px 18px !important;
  }}
}}
</style>
</head>
<body style="margin: 0; padding: 0; background-color: #F1F5F9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #F1F5F9; padding: 32px 10px;">
  <tr>
    <td align="center" valign="top">
      <table class="email-container" width="600" cellpadding="0" cellspacing="0" border="0" style="max-width: 600px; width: 100%; margin: 0 auto; background-color: #FFFFFF; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(15, 23, 42, 0.08); border: 1px solid #E2E8F0;">
        <!-- Header -->
        <tr>
          <td style="background-color: #1F232C; padding: 26px 36px; border-bottom: 3px solid #0F766E;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td valign="middle">
                  <div style="font-size: 20px; font-weight: 800; letter-spacing: 1.5px; color: #FFFFFF; text-transform: uppercase;">
                    VIRTUOSO <span style="color: #14B8A6;">NETSOFT</span>
                  </div>
                  <div style="font-size: 11px; font-weight: 500; letter-spacing: 0.8px; color: #94A3B8; text-transform: uppercase; margin-top: 3px;">
                    IoT &amp; Smart Infrastructure Platform
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <!-- Main Content -->
        <tr>
          <td class="card-body" style="padding: 36px 36px 28px 36px;">
            {content}
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background-color: #F8FAFC; border-top: 1px solid #E2E8F0; padding: 22px 32px; text-align: center;">
            <p style="margin: 0 0 6px 0; font-size: 12px; color: #64748B; line-height: 1.5;">
              This email was sent to <a href="mailto:${{targetEmail}}" style="color: #0F766E; text-decoration: none; font-weight: 500;">${{targetEmail}}</a> by Virtuoso NetSoft.
            </p>
            <p style="margin: 0; font-size: 11.5px; color: #94A3B8;">
              &copy; 2026 Virtuoso NetSoft. All rights reserved.
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

def generate_templates():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    os.makedirs(I18N_DIR, exist_ok=True)

    # 1. activation.ftl (Member Invitation / Activation)
    activation_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A; letter-spacing: -0.3px;">
  Activate Your Account
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  Hello,
</p>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  You have been invited to join the <strong>Virtuoso NetSoft</strong> IoT platform. To confirm your email address and set up your account password, click the button below.
</p>
<p style="margin: 0 0 24px 0; font-size: 13.5px; color: #64748B; line-height: 1.5;">
  This activation link will expire in <strong>${activationLinkTtlInHours} hours</strong>.
</p>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 28px 0;">
  <tr>
    <td align="left">
      <a href="${activationLink}" style="display: inline-block; background-color: #0F766E; color: #FFFFFF; font-size: 14.5px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; box-shadow: 0 2px 8px rgba(15, 118, 110, 0.35);">
        Activate Your Account
      </a>
    </td>
  </tr>
</table>
<p style="margin: 0 0 20px 0; font-size: 13px; color: #64748B; line-height: 1.5;">
  If you are having trouble clicking the button, copy and paste the following URL into your web browser:<br />
  <a href="${activationLink}" style="color: #0F766E; word-break: break-all; font-size: 12.5px;">${activationLink}</a>
</p>
<p style="margin: 0 0 24px 0; font-size: 12.5px; color: #94A3B8; line-height: 1.5; border-top: 1px solid #E2E8F0; padding-top: 18px;">
  If you did not expect this invitation or believe it was sent in error, please disregard this email or contact your platform administrator.
</p>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/activation.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - Account Activation", activation_content))

    # 2. account.activated.ftl
    account_activated_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A; letter-spacing: -0.3px;">
  Account Successfully Activated
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  Congratulations! Your <strong>Virtuoso NetSoft</strong> account has been successfully activated.
</p>
<p style="margin: 0 0 24px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  You can now log in to the platform to access your assigned devices, dashboards, and real-time telemetry analytics.
</p>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 28px 0;">
  <tr>
    <td align="left">
      <a href="${loginLink}" style="display: inline-block; background-color: #0F766E; color: #FFFFFF; font-size: 14.5px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; box-shadow: 0 2px 8px rgba(15, 118, 110, 0.35);">
        Log In to Platform
      </a>
    </td>
  </tr>
</table>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A; border-top: 1px solid #E2E8F0; padding-top: 20px;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/account.activated.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - Account Activated", account_activated_content))

    # 3. reset.password.ftl
    reset_password_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A; letter-spacing: -0.3px;">
  Password Reset Request
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  Hello,
</p>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  We received a request to reset the password for your <strong>Virtuoso NetSoft</strong> account.
</p>
<p style="margin: 0 0 24px 0; font-size: 13.5px; color: #64748B; line-height: 1.5;">
  Click the button below to choose a new password. The link will expire in <strong>${passwordResetLinkTtlInHours} hours</strong>.
</p>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 28px 0;">
  <tr>
    <td align="left">
      <a href="${passwordResetLink}" style="display: inline-block; background-color: #0F766E; color: #FFFFFF; font-size: 14.5px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; box-shadow: 0 2px 8px rgba(15, 118, 110, 0.35);">
        Reset Password
      </a>
    </td>
  </tr>
</table>
<p style="margin: 0 0 20px 0; font-size: 13px; color: #64748B; line-height: 1.5;">
  If you are having trouble clicking the button, copy and paste this URL into your browser:<br />
  <a href="${passwordResetLink}" style="color: #0F766E; word-break: break-all; font-size: 12.5px;">${passwordResetLink}</a>
</p>
<p style="margin: 0 0 24px 0; font-size: 12.5px; color: #94A3B8; line-height: 1.5; border-top: 1px solid #E2E8F0; padding-top: 18px;">
  If you did not request a password reset, no further action is required. Your account remains secure.
</p>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/reset.password.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - Password Reset Request", reset_password_content))

    # 4. password.was.reset.ftl
    password_was_reset_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A; letter-spacing: -0.3px;">
  Password Successfully Reset
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  The password for your <strong>Virtuoso NetSoft</strong> account has been successfully updated.
</p>
<p style="margin: 0 0 24px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  You can now log in to the Virtuoso NetSoft platform using your new password.
</p>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin: 28px 0;">
  <tr>
    <td align="left">
      <a href="${loginLink}" style="display: inline-block; background-color: #0F766E; color: #FFFFFF; font-size: 14.5px; font-weight: 600; text-decoration: none; padding: 14px 32px; border-radius: 8px; box-shadow: 0 2px 8px rgba(15, 118, 110, 0.35);">
        Log In to Platform
      </a>
    </td>
  </tr>
</table>
<p style="margin: 0 0 24px 0; font-size: 12.5px; color: #E11D48; line-height: 1.5; border-top: 1px solid #E2E8F0; padding-top: 18px;">
  <strong>Notice:</strong> If you did not perform this change, please contact your Virtuoso NetSoft system administrator immediately to secure your account.
</p>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/password.was.reset.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - Password Has Been Reset", password_was_reset_content))

    # 5. test.ftl
    test_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A; letter-spacing: -0.3px;">
  SMTP Service Verified
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  This test message confirms that your outgoing SMTP email configuration on the <strong>Virtuoso NetSoft</strong> IoT platform is set up correctly and actively dispatching emails.
</p>
<div style="background-color: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 8px; padding: 14px 18px; margin: 20px 0;">
  <p style="margin: 0; font-size: 13.5px; color: #166534; font-weight: 500;">
    &check; SMTP Connection Status: Operational
  </p>
</div>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A; border-top: 1px solid #E2E8F0; padding-top: 20px;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/test.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - SMTP Test Message", test_content))

    # 6. account.lockout.ftl
    account_lockout_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #E11D48; letter-spacing: -0.3px;">
  Account Lockout Warning
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  The Virtuoso NetSoft user account <strong>${lockoutAccount}</strong> has been temporarily locked out due to multiple failed authentication attempts (more than <strong>${maxFailedLoginAttempts}</strong> attempts).
</p>
<div style="background-color: #FFF1F2; border: 1px solid #FECDD3; border-radius: 8px; padding: 14px 18px; margin: 20px 0;">
  <p style="margin: 0; font-size: 13.5px; color: #9F1239; line-height: 1.5;">
    To protect platform security, logins for this account have been suspended. Please wait for the lockout period to expire or contact your Virtuoso NetSoft platform administrator.
  </p>
</div>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A; border-top: 1px solid #E2E8F0; padding-top: 20px;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/account.lockout.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - Account Lockout Warning", account_lockout_content))

    # 7. 2fa.verification.code.ftl
    twofa_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A; letter-spacing: -0.3px;">
  Two-Factor Authentication Code
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  Use the verification code below to complete your login to <strong>Virtuoso NetSoft</strong>:
</p>
<div style="text-align: center; margin: 28px 0;">
  <div style="display: inline-block; background-color: #F8FAFC; border: 2px dashed #0F766E; border-radius: 10px; padding: 14px 36px; font-size: 30px; font-weight: 800; letter-spacing: 8px; color: #0F766E;">
    ${code}
  </div>
</div>
<p style="margin: 0 0 20px 0; font-size: 13.5px; color: #64748B; text-align: center;">
  This verification code will expire in <strong>${expirationTimeSeconds} seconds</strong>.
</p>
<p style="margin: 0 0 24px 0; font-size: 12.5px; color: #94A3B8; line-height: 1.5; border-top: 1px solid #E2E8F0; padding-top: 18px;">
  If you did not attempt to log in to Virtuoso NetSoft, someone may be trying to access your account. Please secure your account credentials immediately.
</p>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/2fa.verification.code.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - 2FA Verification Code", twofa_content))

    # 8. state.warning.ftl
    state_warning_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #D97706; letter-spacing: -0.3px;">
  Notice: Account Usage Limit
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  Your Virtuoso NetSoft account has reached <strong>${apiValueLabel}</strong>.
</p>
<div style="background-color: #FFFBEB; border: 1px solid #FDE68A; border-radius: 8px; padding: 14px 18px; margin: 20px 0;">
  <p style="margin: 0; font-size: 13.5px; color: #92400E; line-height: 1.5;">
    The feature <strong>${apiFeature}</strong> will be disabled for your account once the configured limit is reached.
  </p>
</div>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A; border-top: 1px solid #E2E8F0; padding-top: 20px;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/state.warning.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - Account Usage Notice", state_warning_content))

    # 9. state.disabled.ftl
    state_disabled_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #DC2626; letter-spacing: -0.3px;">
  Account Feature Restricted
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  The feature <strong>${apiFeature}</strong> has been restricted for your account because Virtuoso NetSoft has reached <strong>${apiLimitValueLabel}</strong>.
</p>
<p style="margin: 0 0 24px 0; font-size: 14px; color: #64748B;">
  Please contact your system administrator or upgrade your service tier to restore access.
</p>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A; border-top: 1px solid #E2E8F0; padding-top: 20px;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/state.disabled.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - Account Feature Restricted", state_disabled_content))

    # 10. state.enabled.ftl
    state_enabled_content = """<h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #059669; letter-spacing: -0.3px;">
  Account Feature Restored
</h2>
<p style="margin: 0 0 16px 0; font-size: 14.5px; color: #334155; line-height: 1.6;">
  The feature <strong>${apiFeature}</strong> for your Virtuoso NetSoft account has been re-enabled and is now able to ${apiLabel} messages.
</p>
<p style="margin: 0; font-size: 14px; font-weight: 600; color: #0F172A; border-top: 1px solid #E2E8F0; padding-top: 20px;">
  &mdash; Virtuoso NetSoft Team
</p>"""
    with open(f"{TEMPLATES_DIR}/state.enabled.ftl", 'w', encoding='utf-8') as f:
        f.write(get_email_wrapper("Virtuoso NetSoft - Account Feature Restored", state_enabled_content))

    # 11. messages.properties
    messages_content = """test.message.subject=Test message from Virtuoso NetSoft
activation.subject=Your account activation on Virtuoso NetSoft
account.activated.subject=Virtuoso NetSoft - your account has been activated
reset.password.subject=Virtuoso NetSoft - Password reset has been requested
password.was.reset.subject=Virtuoso NetSoft - your account password has been reset
account.lockout.subject=Virtuoso NetSoft - User account has been locked
api.usage.state=Virtuoso NetSoft - Account limits
2fa.verification.code.subject=Virtuoso NetSoft - 2FA verification code
"""
    with open(f"{I18N_DIR}/messages.properties", 'w', encoding='utf-8') as f:
        f.write(messages_content)

    print("==> All 10 FreeMarker email templates & messages.properties generated.")

def apply_to_jar():
    print(f"==> Updating {TB_JAR} with Virtuoso NetSoft email templates...")
    t0 = time.time()
    # Update tb.jar directly using zip command
    os.system(f"cd /tmp/tb_patch_classes && zip -r {TB_JAR} BOOT-INF/classes >/dev/null 2>&1")
    print(f"    {TB_JAR} updated in {time.time()-t0:.1f}s")
    if os.path.exists('/tmp/tb_build/thingsboard.jar') and not os.path.samefile(TB_JAR, '/tmp/tb_build/thingsboard.jar'):
        shutil.copy2(TB_JAR, '/tmp/tb_build/thingsboard.jar')

if __name__ == '__main__':
    generate_templates()
    apply_to_jar()
