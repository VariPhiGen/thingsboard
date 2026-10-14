"""Daily check that yesterday's report reached every configured recipient; Telegram alert if not.

Runs from the host crontab (independent of n8n):  python3 -m infra_reports.healthcheck
Exit code 0 = report delivered, 1 = alert raised.
"""
import logging
import sys
from datetime import datetime, timedelta

from .config import REPORT_TZ, load_settings
from .delivery import send_telegram
from .state import STATE_PATH, read_last_success

log = logging.getLogger(__name__)


def check(settings, now=None, path=STATE_PATH):
    """None when yesterday's report was delivered to all recipients, otherwise the problem."""
    now = now or datetime.now(REPORT_TZ)
    expected_day = (now.astimezone(REPORT_TZ).date() - timedelta(days=1)).isoformat()
    record = read_last_success(path)
    if not record:
        return f"no successful report email recorded yet (expected the report for {expected_day})"
    if record.get("report_day") != expected_day:
        return (f"the report for {expected_day} was not emailed; last successful email was the report for "
                f"{record.get('report_day')} sent at {record.get('sent_at')}")
    missing = sorted(set(settings.recipients) - set(record.get("recipients", [])))
    if missing:
        return f"the report for {expected_day} was emailed but not to: {', '.join(missing)}"
    return None


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    problem = check(settings)
    if problem is None:
        log.info("Daily infrastructure report delivered")
        return 0
    log.error("Daily infrastructure report check failed: %s", problem)
    send_telegram(settings, "⚠️ Daily Infrastructure PDF Report NOT delivered\n"
                            f"Checked at: {datetime.now(REPORT_TZ):%d %b %Y %H:%M IST}\nProblem: {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
