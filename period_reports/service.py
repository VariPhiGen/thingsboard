"""Generate a period report file: rollups -> period model -> PDF or Excel."""
import logging
import threading
import time

from infra_reports.config import load_settings
from infra_reports.delivery import render_pdf, resolve_pdf_service
from infra_reports.tb_client import ThingsBoardClient, build_session

from . import rollup
from .period import CATEGORIES, PeriodError, build_period, days_between, fetch_outlook, resolve_period
from .render_pdf import render_html
from .render_xlsx import render_xlsx

log = logging.getLogger(__name__)
FORMATS = {"pdf": "application/pdf",
           "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
# Building missing rollups is heavy: one report build at a time
_build_lock = threading.Lock()


def parse_equipment(value):
    if not value or value == "all":
        return None
    cats = [c.strip() for c in value.split(",") if c.strip()]
    bad = [c for c in cats if c not in CATEGORIES]
    if bad:
        raise PeriodError(f"Unknown equipment: {', '.join(bad)} (use all, {', '.join(CATEGORIES)})")
    return cats


def generate(start, end, equipment="all", fmt="pdf", generated_by=None, settings=None):
    """(bytes, filename, content_type). Raises PeriodError for an invalid request."""
    if fmt not in FORMATS:
        raise PeriodError("Format must be pdf or xlsx")
    s, e = resolve_period(start, end)
    cats = parse_equipment(equipment)
    settings = settings or load_settings()
    t0 = time.time()
    with _build_lock:
        client = ThingsBoardClient.connect(settings)
        rollups = rollup.get_days(days_between(s, e), client, settings)
        devices = [{"id": d["id"]} for d in rollups[-1]["devices"]]
        start_ts, end_ts = rollups[0]["start_ts"], rollups[-1]["end_ts"]
        maint = {}
        for d in devices:
            raw = client.history(d["id"], ["maintenance_record"], start_ts, end_ts).get("maintenance_record", [])
            maint[d["id"]] = rollup._records({"maintenance_record": raw}, "maintenance_record")
        p = build_period(rollups, cats, fetch_outlook(client, devices), generated_by, maintenance_live=maint)
    scope = "all" if not cats else "-".join(cats)
    name = f'Equipment_Report_{p["label"]}_{s:%Y%m%d}' + (f'-{e:%Y%m%d}' if e != s else "") + f"_{scope}.{fmt}"
    if fmt == "pdf":
        data = render_pdf(build_session(settings.http_retries), resolve_pdf_service(settings.pdf_urls),
                          render_html(p), name, timeout=180)
    else:
        data = render_xlsx(p)
    log.info("Period report %s (%d bytes) in %.1fs for %s", name, len(data), time.time() - t0, generated_by)
    return data, name, FORMATS[fmt]
