"""Telegram + email delivery for CMMS alerts (best effort: a failed channel is logged, never raised)."""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from infra_reports.delivery import send_telegram

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, settings, dry_run=False):
        self.s = settings
        self.dry = dry_run
        self.sent = []

    def telegram(self, text):
        self.sent.append(("telegram", text))
        if self.dry:
            log.info("[dry-run] telegram: %s", text.replace("\n", " | ")[:300])
            return True
        return send_telegram(self.s, text)

    def email(self, subject, lines):
        self.sent.append(("email", subject))
        s = self.s
        if self.dry:
            log.info("[dry-run] email: %s", subject)
            return True
        if not (s.smtp_host and s.smtp_user and s.smtp_pass and s.smtp_from and s.recipients):
            log.error("Email not configured (SMTP_* / REPORT_RECIPIENTS); skipped: %s", subject)
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((s.smtp_from_name, s.smtp_from))
        msg["To"] = ", ".join(s.recipients)
        msg.set_content("\n".join(lines))
        msg.add_alternative("<div style='font-family:Arial,sans-serif;font-size:14px;line-height:1.5'>" +
                            "".join(f"<div>{escape(l) if l else '&nbsp;'}</div>" for l in lines) + "</div>", subtype="html")
        try:
            if s.smtp_port == 465:
                server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=30, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30)
                server.starttls(context=ssl.create_default_context())
            with server:
                server.login(s.smtp_user, s.smtp_pass)
                server.send_message(msg)
            return True
        except (smtplib.SMTPException, OSError) as exc:
            log.error("Email '%s' failed: %s", subject, exc.__class__.__name__)
            return False

    def both(self, subject, lines):
        t = self.telegram(subject + "\n\n" + "\n".join(lines))
        e = self.email(subject, lines)
        return t or e
