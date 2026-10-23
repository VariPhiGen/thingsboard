<#--
    SPDX-FileCopyrightText: Copyright The Virtuoso NetSoft Authors
    SPDX-License-Identifier: Apache-2.0
-->
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; box-sizing: border-box; font-size: 14px; margin: 0;">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<title>Virtuoso NetSoft - 2FA Verification Code</title>
<style type="text/css">
body {
  margin: 0;
  padding: 0;
  background-color: #F1F5F9;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -webkit-text-size-adjust: none;
  width: 100% !important;
  height: 100%;
  line-height: 1.6em;
}
@media only screen and (max-width: 620px) {
  .email-container {
    width: 100% !important;
    padding: 10px !important;
  }
  .card-body {
    padding: 24px 18px !important;
  }
}
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
            <h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A; letter-spacing: -0.3px;">
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
</p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background-color: #F8FAFC; border-top: 1px solid #E2E8F0; padding: 22px 32px; text-align: center;">
            <p style="margin: 0 0 6px 0; font-size: 12px; color: #64748B; line-height: 1.5;">
              This email was sent to <a href="mailto:${targetEmail}" style="color: #0F766E; text-decoration: none; font-weight: 500;">${targetEmail}</a> by Virtuoso NetSoft.
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
</html>