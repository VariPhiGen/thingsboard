"""Fetch -> render -> PDF -> email, failing closed at every step."""
import logging
from datetime import datetime

from .collect import collect_summary, period_of
from .config import REPORT_TZ, load_settings
from .delivery import ReportError, render_pdf, resolve_pdf_service
from .reports import REPORTS
from .tb_client import ThingsBoardClient, build_session

log = logging.getLogger(__name__)


def report_day(summary):
    """IST date the report is about (the report day, or today for the rolling 24h report)."""
    start_ts, _, historical = period_of(summary)
    return datetime.fromtimestamp(start_ts / 1000, REPORT_TZ) if historical else datetime.now(REPORT_TZ)


def fetch_summary(report_date=None, settings=None):
    settings = settings or load_settings()
    client = ThingsBoardClient.connect(settings)
    summary = collect_summary(client, settings.profiles, report_date)
    log.info("Collected %d report device(s) for %s", len(summary), report_date or "the last 24 hours")
    return summary


def build_reports(summary, settings=None, session=None):
    """Render all four reports to PDF. Raises ReportError if any report fails."""
    settings = settings or load_settings()
    session = session or build_session(settings.http_retries)
    day = report_day(summary)
    date_fn = day.strftime("%Y%m%d")
    service_url = resolve_pdf_service(settings.pdf_urls)

    reports = []
    for report_id, name, file_prefix, render_html in REPORTS:
        filename = f"{file_prefix}_{date_fn}.pdf"
        html = render_html(summary)
        log.info("Generating PDF %s", filename)
        reports.append({
            "id": report_id, "name": name, "filename": filename, "html": html, "report_day": day,
            "pdf_bytes": render_pdf(session, service_url, html, filename),
        })
    return reports


__all__ = ["ReportError", "build_reports", "fetch_summary", "report_day"]
