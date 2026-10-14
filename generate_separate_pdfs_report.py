#!/usr/bin/env python3
"""Daily 24-hour infrastructure PDF reports: CLI and the API used by the n8n report service.

The implementation lives in the `infra_reports` package. The three functions below keep the
signatures that /home/ubuntu/vgi-cron-email-script/n8n_report_api.py imports; they raise on
failure (so the n8n run fails visibly) and send a Telegram alert when one is configured.
"""
import argparse
import logging
import sys
from pathlib import Path

from infra_reports.config import ConfigError, load_settings, parse_recipients
from infra_reports.delivery import send_email, send_failure_alert
from infra_reports.metrics import resolve_report_date
from infra_reports.pipeline import build_reports, fetch_summary, report_day

log = logging.getLogger("infra_reports")

DEFAULT_PREVIEW_DIR = Path(__file__).resolve().parent / "report_previews"


def _alerting(stage, func, *args, **kwargs):
    """Run one stage of the scheduled report; alert and re-raise if it fails."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        try:
            settings = load_settings()
        except ConfigError:
            settings = None
        send_failure_alert(settings, stage, exc)
        raise


def fetch_master_devices_summary(report_date=None):
    """Per-device telemetry, 24h statistics, graph series and alarms.
    report_date: 'yesterday', 'YYYY-MM-DD' (IST day) or None (last 24 hours)."""
    # A malformed date is a caller error (ValueError), not an operational failure: no alert
    report_date = resolve_report_date(report_date)
    return _alerting("fetch ThingsBoard data", fetch_summary, report_date)


def generate_all_separate_pdfs(summary=None):
    """Render the 4 reports to PDF; raises ReportError if any one fails."""
    if summary is None:
        summary = fetch_master_devices_summary()
    return _alerting("generate PDFs", build_reports, summary)


def send_email_with_separate_pdfs(reports, recipients_override=None, report_day=None):
    """Email all PDFs in one message; returns True, raises on failure."""
    def _send():
        settings = load_settings()
        recipients = parse_recipients(recipients_override) if recipients_override else settings.recipients
        return send_email(settings, reports, recipients, report_day)
    return _alerting("send email", _send)


def write_previews(reports, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for r in reports:
        (out_dir / f"{r['id']}_24h_preview.html").write_text(r["html"], encoding="utf-8")
        pdf_path = out_dir / f"{r['id']}_24h_preview.pdf"
        pdf_path.write_bytes(r["pdf_bytes"])
        log.info("Preview written: %s (%d bytes)", pdf_path, len(r["pdf_bytes"]))


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Daily 24-hour infrastructure PDF reports")
    parser.add_argument("--preview", action="store_true", help="write HTML + PDF previews to --out-dir")
    parser.add_argument("--send", "--send-now", dest="send", action="store_true", help="email the PDFs")
    parser.add_argument("--to", help="comma-separated recipients (default: REPORT_RECIPIENTS)")
    parser.add_argument("--date", help="report on one past IST day: YYYY-MM-DD or 'yesterday' (default: last 24 hours)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_PREVIEW_DIR, help="preview directory")
    parser.add_argument("--alert", action="store_true", help="send a Telegram alert on failure (scheduled runs)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not (args.preview or args.send):
        parser.error("nothing to do: pass --preview and/or --send")
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stage = "start"
    try:
        settings = load_settings()
        recipients = parse_recipients(args.to) if args.to else settings.recipients
        stage = "fetch ThingsBoard data"
        summary = fetch_summary(args.date, settings)
        stage = "generate PDFs"
        reports = build_reports(summary, settings)
        if args.preview:
            write_previews(reports, args.out_dir)
        if args.send:
            stage = "send email"
            send_email(settings, reports, recipients, report_day(summary))
    except Exception as exc:
        log.error("Report failed at %s: %s", stage, exc)
        if args.alert:
            try:
                send_failure_alert(load_settings(), stage, exc)
            except ConfigError:
                send_failure_alert(None, stage, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
