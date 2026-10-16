"""Pure calculations on raw telemetry: parsing, 30-min buckets, statistics, energy."""
import time
from datetime import datetime, timedelta

from .config import REPORT_TZ

BUCKET_MS = 30 * 60 * 1000
# Values controllers send when a sensor is absent/faulty (Modbus 0x7FFF / 0xFFFF)
SENSOR_OFFLINE_VALUES = {32767.0, 65535.0}
# Power samples further apart than this are a data gap: the load in between is unknown
MAX_POWER_GAP_MS = 5 * 60 * 1000
# A DG delivering more than this is running (same threshold as the rule chain's DG status)
RUNNING_KW = 5.0
# A stop shorter than this does not end a run (the rule chain also needs 2 min of OFF)
MIN_STOP_MS = 2 * 60 * 1000


def resolve_report_date(report_date, now=None):
    """'yesterday' -> the previous IST date as 'YYYY-MM-DD'; other values are validated and returned."""
    if not report_date:
        return None
    if report_date.strip().lower() == "yesterday":
        now = now or datetime.now(REPORT_TZ)
        return (now.astimezone(REPORT_TZ).date() - timedelta(days=1)).isoformat()
    datetime.strptime(report_date, "%Y-%m-%d")  # raises ValueError on a bad date
    return report_date


def report_window(report_date=None, now_ms=None):
    """(start_ms, end_ms): the last 24 hours, or the IST calendar day 'YYYY-MM-DD' / 'yesterday'."""
    report_date = resolve_report_date(report_date)
    if not report_date:
        end_ts = now_ms if now_ms is not None else int(time.time() * 1000)
        return end_ts - 24 * 3600 * 1000, end_ts
    day = datetime.strptime(report_date, "%Y-%m-%d").replace(tzinfo=REPORT_TZ)
    return int(day.timestamp() * 1000), int((day + timedelta(days=1)).timestamp() * 1000)


def parse_value(value):
    """Telemetry value -> float. Booleans become 1.0/0.0; text, errors and sensor-offline codes -> None."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    text = str(value).strip().lower()
    if text in ("true", "false"):
        return 1.0 if text == "true" else 0.0
    try:
        number = float(text)
    except (ValueError, TypeError):
        return None
    if number in SENSOR_OFFLINE_VALUES or number != number:  # NaN check
        return None
    return number


def valid_samples(points):
    """ThingsBoard [{'ts', 'value'}] -> [(ts, float)] sorted by time, invalid values dropped."""
    samples = []
    for point in points:
        number = parse_value(point.get("value"))
        if number is not None:
            samples.append((int(point["ts"]), number))
    samples.sort()
    return samples


def bucket_series(samples, start_ts, end_ts, bucket_ms=BUCKET_MS):
    """Average of samples per bucket; None where a bucket has no sample."""
    n = max(int((end_ts - start_ts) // bucket_ms), 1)
    sums, counts = [0.0] * n, [0] * n
    for ts, value in samples:
        i = int((ts - start_ts) // bucket_ms)
        if 0 <= i < n:
            sums[i] += value
            counts[i] += 1
    return [sums[i] / counts[i] if counts[i] else None for i in range(n)]


def sample_stats(samples):
    """avg/min/max/delta(last-first)/count of samples; {} when there are none."""
    if not samples:
        return {}
    values = [v for _, v in samples]
    return {
        "avg": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "delta": values[-1] - values[0],
        "count": len(values),
    }


def integrate_energy_kwh(power_samples, start_ts, end_ts, max_gap_ms=MAX_POWER_GAP_MS):
    """Energy (kWh) from power samples (kW) by the trapezoidal rule, plus the fraction of the
    window covered by data. Intervals longer than max_gap_ms are skipped (load unknown)."""
    samples = [(ts, kw) for ts, kw in power_samples if start_ts <= ts < end_ts and kw >= 0]
    energy_kwh, covered_ms = 0.0, 0
    for (t0, p0), (t1, p1) in zip(samples, samples[1:]):
        dt = t1 - t0
        if 0 < dt <= max_gap_ms:
            energy_kwh += (p0 + p1) / 2 * dt / 3_600_000
            covered_ms += dt
    window = end_ts - start_ts
    return energy_kwh, (covered_ms / window if window > 0 else 0.0)


def count_runs(power_samples, start_ts, end_ts, rpm_samples=(), threshold_kw=RUNNING_KW, threshold_rpm=100,
               min_stop_ms=MIN_STOP_MS):
    """Number of separate engine runs in [start_ts, end_ts).

    At each timestamp the engine runs when RPM is above threshold_rpm or power above threshold_kw,
    so a run without load still counts. Sensor-offline RPM codes and failed reads are not readings.
    A stop shorter than min_stop_ms (a read error, a dip in the data) does not end a run, and a data
    gap does not split one. A run already going at start_ts counts once."""
    readings = {}
    for ts, kw in power_samples:
        readings.setdefault(ts, {})["power"] = kw
    for ts, rpm in rpm_samples:
        if rpm not in SENSOR_OFFLINE_VALUES:
            readings.setdefault(ts, {})["rpm"] = rpm
    runs, last_running_ts = 0, None
    for ts in sorted(readings):
        if not start_ts <= ts < end_ts:
            continue
        r = readings[ts]
        if r.get("rpm", 0) > threshold_rpm or r.get("power", 0) > threshold_kw:
            if last_running_ts is None or ts - last_running_ts > min_stop_ms:
                stopped_since = None if last_running_ts is None else last_running_ts
                # A gap with no readings at all is not a stop: only count a new run after a seen stop
                if stopped_since is None or _seen_stop(readings, stopped_since, ts, threshold_kw, threshold_rpm):
                    runs += 1
            last_running_ts = ts
    return runs


def _seen_stop(readings, after_ts, before_ts, threshold_kw, threshold_rpm):
    """True when a reading strictly between the two timestamps shows a stopped engine."""
    return any(after_ts < ts < before_ts and r.get("rpm", 0) <= threshold_rpm and r.get("power", 0) <= threshold_kw
               for ts, r in readings.items())
