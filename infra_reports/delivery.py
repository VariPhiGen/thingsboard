"""PDF rendering, email delivery and failure alerts."""
import logging
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import requests

from .config import REPORT_TZ, ConfigError
from .state import record_success

log = logging.getLogger(__name__)

SMTP_ATTEMPTS = 3
SMTP_TIMEOUT = 30


class ReportError(RuntimeError):
    """A report could not be produced or delivered; nothing partial is sent."""


# ------------------------------------------------------------------ PDF
def resolve_pdf_service(urls):
    """First pdf-generator URL whose /health answers, or 'local' if wkhtmltopdf is installed."""
    for url in urls:
        try:
            if requests.get(f"{url}/health", timeout=(2, 5)).ok:
                return url
        except requests.RequestException:
            continue
    import shutil
    if shutil.which("wkhtmltopdf"):
        return "local"
    raise ReportError(f"PDF generator unreachable (tried {', '.join(urls)})")


def render_pdf(session, service_url, html, filename, timeout=120):
    """HTML -> PDF bytes via local wkhtmltopdf or the pdf-generator service; raises ReportError on any failure."""
    if service_url == "local":
        import subprocess
        import tempfile
        import os
        try:
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as html_f:
                html_f.write(html)
                html_path = html_f.name
            pdf_path = html_path.replace(".html", ".pdf")
            cmd = [
                "wkhtmltopdf",
                "--disable-javascript",
                "--page-size", "A4",
                "--margin-top", "10mm",
                "--margin-bottom", "10mm",
                "--margin-left", "10mm",
                "--margin-right", "10mm",
                html_path,
                pdf_path,
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
            if res.returncode == 0 and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                try: os.remove(html_path)
                except Exception: pass
                try: os.remove(pdf_path)
                except Exception: pass
                if pdf_bytes.startswith(b"%PDF"):
                    return pdf_bytes
        except Exception as exc:
            raise ReportError(f"Local PDF generation failed for {filename}: {exc}") from exc
        raise ReportError(f"Local PDF generation failed for {filename}")

    try:
        res = session.post(f"{service_url}/render-raw-html-pdf", json={"html": html}, timeout=(5, timeout))
    except requests.RequestException as exc:
        raise ReportError(f"PDF generation failed for {filename}: {exc}") from exc
    if res.status_code != 200:
        raise ReportError(f"PDF generation failed for {filename}: HTTP {res.status_code} {res.text[:200]}")
    if not res.content.startswith(b"%PDF"):
        raise ReportError(f"PDF generation for {filename} returned non-PDF content")
    return res.content


# ------------------------------------------------------------------ email
def build_message(settings, reports, recipients, report_day):
    date_str = report_day.strftime("%d %b %Y")
    msg = EmailMessage()
    msg["Subject"] = f"📑 Daily 24-Hour Infrastructure PDF Reports — {date_str} ({len(reports)} PDF Attachments)"
    msg["From"] = formataddr((settings.smtp_from_name, settings.smtp_from))
    msg["To"] = ", ".join(recipients)
    msg["Message-ID"] = make_msgid(domain=settings.smtp_from.split("@")[-1])

    items_text = "\n".join(f"  {i}. {r['name']} ({r['filename']})" for i, r in enumerate(reports, 1))
    items_html = "".join(f"<li><b>{i}. {r['name']}</b> (<code>{r['filename']}</code>)</li>" for i, r in enumerate(reports, 1))
    msg.set_content(
        f"Daily 24-Hour Master Infrastructure Reports\nDate: {date_str}\n\n"
        f"Attached are {len(reports)} PDF reports covering the 24-hour infrastructure records:\n{items_text}\n\n"
        "Automated Infrastructure Operations - Virtuoso NetSoft\n"
    )
    msg.add_alternative(f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #f4f6f9; margin:0; padding:20px;">
    <div style="max-width: 800px; margin:0 auto; background:#ffffff; border-radius:8px; padding:25px;">
        <h2 style="color: #0f172a; margin-top:0;">🏢 Daily 24-Hour Master Infrastructure Reports</h2>
        <p style="color: #475569; font-size:14px;">Date: <b>{date_str}</b></p>
        <p style="color: #334155; font-size:14px;">Please find attached the <b>{len(reports)} separate PDF reports</b> covering the 24-hour infrastructure records:</p>
        <ul style="line-height:1.8; color: #1e293b; font-size:14px;">{items_html}</ul>
        <hr style="border:0; border-top:1px solid #e2e8f0; margin:20px 0;" />
        <p style="font-size:12px; color:#94a3b8; text-align:center;">Automated Infrastructure Operations • Virtuoso NetSoft</p>
    </div>
</body>
</html>""", subtype="html")
    for r in reports:
        msg.add_attachment(r["pdf_bytes"], maintype="application", subtype="pdf", filename=r["filename"])
    return msg


def _transient(exc):
    if isinstance(exc, smtplib.SMTPResponseException):
        return 400 <= exc.smtp_code < 500
    return isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError))


def send_email(settings, reports, recipients, report_day=None):
    """Send all reports in one email. Raises ReportError unless every PDF is present and SMTP accepts it."""
    if not recipients:
        raise ConfigError("No report recipients configured (REPORT_RECIPIENTS)")
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_pass and settings.smtp_from):
        raise ConfigError("SMTP settings incomplete (SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_FROM)")
    missing = [r["filename"] for r in reports if not r.get("pdf_bytes")]
    if missing:
        raise ReportError(f"Refusing to send: PDF missing for {', '.join(missing)}")

    report_day = report_day or reports[0].get("report_day") or datetime.now(REPORT_TZ)
    msg = build_message(settings, reports, recipients, report_day)
    context = ssl.create_default_context()
    for attempt in range(1, SMTP_ATTEMPTS + 1):
        try:
            if settings.smtp_port == 465:
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT, context=context)
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT)
                server.starttls(context=context)
            with server:
                server.login(settings.smtp_user, settings.smtp_pass)
                refused = server.send_message(msg, from_addr=settings.smtp_from, to_addrs=recipients)
            if refused:
                log.warning("SMTP refused some recipients: %s", ", ".join(refused))
            delivered = [r for r in recipients if r not in refused]
            log.info("Email with %d PDF(s) sent to %s", len(reports), ", ".join(delivered))
            try:
                record_success(report_day, delivered, [r["filename"] for r in reports])
            except OSError as exc:
                log.warning("Could not record the successful send for the health check: %s", exc)
            return True
        except smtplib.SMTPException as exc:
            if not _transient(exc) or attempt == SMTP_ATTEMPTS:
                raise ReportError(f"Email delivery failed: {exc}") from exc
            log.warning("SMTP attempt %d failed (%s); retrying", attempt, exc)
        except OSError as exc:
            if attempt == SMTP_ATTEMPTS:
                raise ReportError(f"Email delivery failed: {exc}") from exc
            log.warning("SMTP attempt %d failed (%s); retrying", attempt, exc)
        time.sleep(5 * attempt)


# ------------------------------------------------------------------ alerts
def send_telegram(settings, text):
    """Best-effort Telegram message to every configured chat; True if all were accepted. Never raises."""
    if not (settings and settings.telegram_bot_token and settings.telegram_chat_ids):
        log.error("No Telegram alert configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); message: %s", text)
        return False
    ok = True
    for chat_id in settings.telegram_chat_ids:
        try:
            res = requests.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                                json={"chat_id": chat_id, "text": text}, timeout=10)
            if res.status_code != 200:
                ok = False
                log.error("Telegram alert to %s rejected: HTTP %s", chat_id, res.status_code)
        except requests.RequestException as exc:
            ok = False
            log.error("Telegram alert to %s failed: %s", chat_id, exc.__class__.__name__)
    return ok


def send_failure_alert(settings, stage, error):
    """Telegram alert when the scheduled report fails; never raises."""
    send_telegram(settings, f"⚠️ Daily Infrastructure PDF Report FAILED\nStage: {stage}\n"
                            f"Time: {datetime.now(REPORT_TZ):%d %b %Y %H:%M IST}\nError: {str(error)[:500]}\n"
                            "No (partial) email was sent.")
