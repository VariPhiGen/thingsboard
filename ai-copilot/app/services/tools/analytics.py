from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.tb_client import ThingsBoardClient
from app.services.tools.telemetry import DISPLAY, keys_for_device, normalize_value
from app.services.time_window import TimeWindow, extract_metric_keys


def _to_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        num = float(raw)
    except Exception:
        return None
    if num >= 30000:
        return None
    return num


def _series_values(points: list[dict[str, Any]]) -> list[tuple[int, float]]:
    # TB returns newest-first usually
    out: list[tuple[int, float]] = []
    for p in points or []:
        val = _to_float(p.get("value"))
        ts = p.get("ts")
        if val is None or not isinstance(ts, int):
            continue
        out.append((ts, val))
    out.sort(key=lambda x: x[0])
    return out


def compute_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "avg": round(sum(values) / len(values), 3),
        "first": round(values[0], 3),
        "last": round(values[-1], 3),
    }


def compute_trend(series: list[tuple[int, float]]) -> dict[str, Any]:
    if len(series) < 2:
        return {"direction": "insufficient_data", "change": None, "change_pct": None}
    first = series[0][1]
    last = series[-1][1]
    change = last - first
    change_pct = (change / first * 100.0) if first != 0 else None
    # simple slope using endpoints
    if abs(change) < 1e-9:
        direction = "stable"
    elif change > 0:
        direction = "rising"
    else:
        direction = "falling"
    return {
        "direction": direction,
        "change": round(change, 3),
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "from": round(first, 3),
        "to": round(last, 3),
        "points": len(series),
    }


def estimate_running_duration_ms(status_series: list[tuple[int, float]] | None, rpm_series: list[tuple[int, float]] | None) -> dict[str, Any]:
    """Estimate running duration from rpm>100 or dg_status==1 samples."""
    series = rpm_series or status_series or []
    if len(series) < 2:
        return {"running_ms": 0, "running_hours": 0.0, "samples": len(series), "method": "insufficient_data"}

    running_ms = 0
    method = "engine_rpm" if rpm_series else "dg_status"
    for i in range(1, len(series)):
        prev_ts, prev_val = series[i - 1]
        ts, val = series[i]
        dt = max(0, ts - prev_ts)
        active = val > 100 if method == "engine_rpm" else val >= 1
        if active:
            running_ms += dt
    hours = round(running_ms / 3_600_000, 2)
    return {
        "running_ms": running_ms,
        "running_hours": hours,
        "samples": len(series),
        "method": method,
    }


async def fetch_window_series(
    client: ThingsBoardClient,
    device_id: UUID,
    device_name: str,
    window: TimeWindow,
    message: str,
    device_type: str | None = None,
) -> dict[str, Any]:
    all_keys = keys_for_device(device_name, device_type)
    keys = extract_metric_keys(message, all_keys)
    # include status/rpm for duration analysis
    for extra in ("dg_status", "engine_rpm"):
        if extra in all_keys and extra not in keys:
            keys.append(extra)

    span = max(1, window.end_ts - window.start_ts)
    # aim for ~60 buckets
    interval = max(60_000, span // 60)
    raw = await client.history_telemetry(
        device_id,
        keys,
        window.start_ts,
        window.end_ts,
        limit=200,
        interval=interval,
        agg="AVG",
    )
    return {"keys": keys, "raw": raw or {}, "interval_ms": interval}


def analyze_window(
    device_name: str,
    window: TimeWindow,
    series_payload: dict[str, Any],
    mode: str,
) -> str:
    raw = series_payload.get("raw") or {}
    keys = series_payload.get("keys") or []
    lines = [
        f"Analysis window: {window.label}",
        f"Device: {device_name}",
        f"Mode: {mode}",
    ]

    stats_block: list[str] = []
    trend_block: list[str] = []
    rpm_series = _series_values(raw.get("engine_rpm") or [])
    status_series = _series_values(raw.get("dg_status") or [])

    for key in keys:
        series = _series_values(raw.get(key) or [])
        label = DISPLAY.get(key, key)
        vals = [v for _, v in series]
        st = compute_stats(vals)
        tr = compute_trend(series)
        if st.get("count"):
            stats_block.append(
                f"- {label}: min={st['min']}, max={st['max']}, avg={st['avg']}, last={st['last']} (n={st['count']})"
            )
            trend_block.append(
                f"- {label}: {tr['direction']} ({tr.get('from')} → {tr.get('to')}, Δ={tr.get('change')}"
                + (f", {tr['change_pct']}%" if tr.get("change_pct") is not None else "")
                + ")"
            )
        else:
            stats_block.append(f"- {label}: no valid samples in this window")

    if mode in {"statistics", "time", "date", "shift", "general"}:
        lines.append("Statistics:")
        lines.extend(stats_block or ["- none"])

    if mode in {"trend", "time", "date", "shift", "general"}:
        lines.append("Trend:")
        lines.extend(trend_block or ["- none"])

    if mode in {"duration", "shift", "date", "time", "general"}:
        dur = estimate_running_duration_ms(status_series, rpm_series)
        lines.append(
            f"Estimated running duration: {dur['running_hours']} hours "
            f"(method={dur['method']}, samples={dur['samples']})"
        )

    return "\n".join(lines)


async def compare_periods(
    client: ThingsBoardClient,
    device_id: UUID,
    device_name: str,
    message: str,
    window_a: TimeWindow,
    window_b: TimeWindow,
    device_type: str | None = None,
) -> str:
    a = await fetch_window_series(client, device_id, device_name, window_a, message, device_type)
    b = await fetch_window_series(client, device_id, device_name, window_b, message, device_type)
    keys = extract_metric_keys(message, a.get("keys") or [])
    lines = [
        f"Comparison for {device_name}",
        f"Period A: {window_a.label}",
        f"Period B: {window_b.label}",
    ]
    for key in keys:
        sa = compute_stats([v for _, v in _series_values((a.get("raw") or {}).get(key) or [])])
        sb = compute_stats([v for _, v in _series_values((b.get("raw") or {}).get(key) or [])])
        label = DISPLAY.get(key, key)
        if not sa.get("count") and not sb.get("count"):
            lines.append(f"- {label}: no data in either period")
            continue
        avg_a = sa.get("avg")
        avg_b = sb.get("avg")
        delta = None if avg_a is None or avg_b is None else round(avg_b - avg_a, 3)
        lines.append(
            f"- {label}: A avg={avg_a if avg_a is not None else 'n/a'}, "
            f"B avg={avg_b if avg_b is not None else 'n/a'}, Δ={delta if delta is not None else 'n/a'}"
        )
    return "\n".join(lines)


async def compare_devices(
    client: ThingsBoardClient,
    devices: list[tuple[UUID, str, str | None]],
    message: str,
    window: TimeWindow,
) -> str:
    lines = [f"Device comparison over {window.label}"]
    for device_id, name, dtype in devices:
        payload = await fetch_window_series(client, device_id, name, window, message, dtype)
        lines.append(f"\n{name}:")
        raw = payload.get("raw") or {}
        for key in extract_metric_keys(message, payload.get("keys") or []):
            st = compute_stats([v for _, v in _series_values(raw.get(key) or [])])
            label = DISPLAY.get(key, key)
            if st.get("count"):
                lines.append(f"- {label}: avg={st['avg']}, min={st['min']}, max={st['max']}")
            else:
                lines.append(f"- {label}: no valid samples")
    return "\n".join(lines)
