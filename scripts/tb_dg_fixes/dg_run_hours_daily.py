"""Daily DG running-hour history as clean telemetry, for the "Run hours history" widgets on the DG dashboards.

Why: DG devices store failed Modbus reads as the text 'error' in run_hours (about 1 sample in 5), and a ThingsBoard
aggregation (MAX/MIN/AVG) over a day returns 'error' as soon as one such sample is in the window. So the history is
computed here from the raw samples (numeric ones only) and saved as two numeric keys per IST day, stamped at the
IST day start:

  run_hours_daily  hours the engine ran that day  = total at day end - total at previous day end (0..24, like the
                   daily rollups of period_reports; a day outside that range is not written)
  run_hours_eod    engine hour-meter reading at day end

Devices are those of the DG device profiles of infra_reports (settings), so nothing is listed here by hand.
Re-running rewrites the same timestamps (idempotent). The current IST day is partial and is refreshed on each run.

  dg_run_hours_daily.py --days 90            dry run: print what would be written
  dg_run_hours_daily.py --days 90 --apply    write
  dg_run_hours_daily.py --apply              last 3 days (the scheduled run)
"""
import argparse
import logging
import re
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, "/home/ubuntu/thingsboard")
from infra_reports.collect import classify  # noqa: E402
from infra_reports.config import REPORT_TZ, load_settings  # noqa: E402
from infra_reports.tb_client import ThingsBoardClient  # noqa: E402

KEY = "run_hours"
DAILY, EOD = "run_hours_daily", "run_hours_eod"
SAMPLE_LIMIT = 200                  # newest samples looked at per day end; ~1 in 5 is 'error', so a number is always among them
LOOKBACK_DAYS = 30                  # a DG that was offline at the day end: last reading up to this far back
MAX_DAILY_H = 24
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def day_start_ms(d):
    return int(datetime.combine(d, time.min, tzinfo=REPORT_TZ).timestamp() * 1000)


def eod_reading(client, dev_id, end_ms):
    """Last numeric run_hours reading before end_ms (hours), or None."""
    raw = client._get(f"/api/plugins/telemetry/DEVICE/{dev_id}/values/timeseries", {
        "keys": KEY, "startTs": end_ms - LOOKBACK_DAYS * 86400000, "endTs": end_ms, "limit": SAMPLE_LIMIT, "orderBy": "DESC"})
    for p in raw.get(KEY, []):
        if _NUM.match(str(p["value"]).strip()):
            return float(p["value"])
    return None


def history(client, dev_id, days, today):
    """[(day_start_ms, daily_hours|None, eod|None)] oldest first, for the last `days` IST days up to today."""
    dates = [today - timedelta(days=i) for i in range(days, -1, -1)]          # one extra day at the start: its eod is the base
    eods = {d: eod_reading(client, dev_id, day_start_ms(d + timedelta(days=1))) for d in dates}
    now_ms = int(datetime.now(REPORT_TZ).timestamp() * 1000)
    if today in eods:                                                           # today ends now, not at midnight
        eods[today] = eod_reading(client, dev_id, now_ms)
    rows = []
    for prev, d in zip(dates, dates[1:]):
        e, p = eods[d], eods[prev]
        delta = round(e - p, 2) if e is not None and p is not None else None
        if delta is not None and not 0 <= delta <= MAX_DAILY_H:
            delta = None
        rows.append((day_start_ms(d), delta, round(e, 2) if e is not None else None))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=3, help="IST days back from today (default 3)")
    ap.add_argument("--apply", action="store_true", help="write the telemetry (default: dry run)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    settings = load_settings()
    client = ThingsBoardClient.connect(settings)
    today = datetime.now(REPORT_TZ).date()
    devices = [d for d in client.devices() if classify(d, settings.profiles) == "dg"]
    if not devices:
        sys.exit("no DG devices found")
    for dev in devices:
        rows = history(client, dev["id"]["id"], a.days, today)
        writable = [r for r in rows if r[1] is not None or r[2] is not None]
        print(f"{dev['name']}: {len(writable)} of {len(rows)} days have data; "
              f"total run hours {round(sum(r[1] or 0 for r in rows), 1)}")
        for ts, daily, eod in rows[-5:]:
            print("   ", datetime.fromtimestamp(ts / 1000, REPORT_TZ).date(), daily, eod)
        if not a.apply:
            continue
        body = []
        for ts, daily, eod in writable:
            values = {k: v for k, v in ((DAILY, daily), (EOD, eod)) if v is not None}
            body.append({"ts": ts, "values": values})
        res = client.session.post(f"{client.base_url}/api/plugins/telemetry/DEVICE/{dev['id']['id']}/timeseries/ANY",
                                  json=body, headers=client._headers, timeout=120)
        print("    written:" if res.ok else "    FAILED:", res.status_code, "" if res.ok else res.text[:200])
        if not res.ok:
            sys.exit(1)
    if not a.apply:
        print("dry run: nothing written (use --apply)")


if __name__ == "__main__":
    main()
