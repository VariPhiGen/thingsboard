#!/usr/bin/env python3
"""
Delhivery daily alarm + telemetry report for ThingsBoard CE.

Generates:
  - alarms.csv
  - telemetry_latest.csv
  - report.pdf
  - summary.json

Auth: sysadmin login → impersonate Delhivery tenant admin token.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TB_URL = os.environ.get("TB_URL", "http://127.0.0.1:9091").rstrip("/")
TB_SYSADMIN_USER = os.environ.get("TB_SYSADMIN_USER", "sysadmin@thingsboard.org")
TB_SYSADMIN_PASSWORD = os.environ.get("TB_SYSADMIN_PASSWORD", "sysadmin")
# Delhivery tenant admin on Virtuoso TB
DELHIVERY_USER_ID = os.environ.get(
    "TB_DELHIVERY_USER_ID", "1db727e0-6a70-11f1-87c3-df6f31aa9de9"
)
REPORT_TZ = os.environ.get("REPORT_TZ", "Asia/Kolkata")

# Real devices on Delhivery tenant (no demo/simulated devices)
DEVICE_NAMES = [
    "DG SET1",
    "gateway001",
]

TELEMETRY_KEYS = [
    "power_kw",
    "energy_kwh",
    "run_hours",
    "engine_starts",
    "engine_rpm",
    "coolant_temp",
    "oil_pressure",
    "battery_voltage",
    "voltage",
    "voltage_delta",
    "current",
    "frequency",
    "power_factor",
    "status",
    "anomaly",
    "summary",
]


def tzinfo():
    if ZoneInfo is None:
        return timezone(timedelta(hours=5, minutes=30))
    return ZoneInfo(REPORT_TZ)


def now_local() -> datetime:
    return datetime.now(tzinfo())


def http_json(method: str, path: str, token: str | None = None, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{TB_URL}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"{method} {path} -> {e.code}: {err[:500]}") from e


def login_sysadmin() -> str:
    data = http_json(
        "POST",
        "/api/auth/login",
        body={"username": TB_SYSADMIN_USER, "password": TB_SYSADMIN_PASSWORD},
    )
    return data["token"]


def tenant_token(sys_token: str) -> str:
    data = http_json("GET", f"/api/user/{DELHIVERY_USER_ID}/token", token=sys_token)
    return data["token"]


def fetch_devices(token: str) -> list[dict]:
    page = 0
    out: list[dict] = []
    while True:
        data = http_json(
            "GET",
            f"/api/tenant/devices?pageSize=100&page={page}",
            token=token,
        )
        out.extend(data.get("data") or [])
        if not data.get("hasNext"):
            break
        page += 1
    return out


def fetch_alarms(token: str, start_ms: int, end_ms: int) -> list[dict]:
    """Fetch alarms updated/created in window (ACTIVE + CLEARED)."""
    page = 0
    out: list[dict] = []
    while True:
        path = (
            f"/api/v2/alarms?pageSize=100&page={page}"
            f"&startTime={start_ms}&endTime={end_ms}"
            f"&fetchOriginator=true"
        )
        data = http_json("GET", path, token=token)
        out.extend(data.get("data") or [])
        if not data.get("hasNext"):
            break
        page += 1
        if page > 50:
            break
    return out


def fetch_latest_telemetry(token: str, device_id: str, keys: list[str]) -> dict:
    key_q = ",".join(keys)
    path = (
        f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries"
        f"?keys={key_q}&useStrictDataTypes=true"
    )
    try:
        return http_json("GET", path, token=token) or {}
    except RuntimeError:
        return {}


def ms_to_local(ms: int | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tzinfo()).strftime("%Y-%m-%d %H:%M:%S %Z")


def write_alarms_csv(path: Path, alarms: list[dict]) -> None:
    fields = [
        "created_time",
        "start_time",
        "end_time",
        "type",
        "severity",
        "status",
        "originator",
        "details",
        "acknowledged",
        "cleared",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for a in alarms:
            details = a.get("details") or {}
            if isinstance(details, dict):
                details_s = details.get("data") or json.dumps(details)
            else:
                details_s = str(details)
            status = a.get("status")
            if not status:
                ack = a.get("acknowledged")
                cleared = a.get("cleared")
                status = (
                    ("CLEARED" if cleared else "ACTIVE")
                    + "_"
                    + ("ACK" if ack else "UNACK")
                )
            w.writerow(
                {
                    "created_time": ms_to_local(a.get("createdTime")),
                    "start_time": ms_to_local(a.get("startTs")),
                    "end_time": ms_to_local(a.get("endTs")),
                    "type": a.get("type") or a.get("name") or "",
                    "severity": a.get("severity") or "",
                    "status": status,
                    "originator": a.get("originatorName")
                    or a.get("originatorDisplayName")
                    or "",
                    "details": details_s,
                    "acknowledged": a.get("acknowledged"),
                    "cleared": a.get("cleared"),
                }
            )


def write_telemetry_csv(path: Path, rows: list[dict]) -> None:
    fields = ["device", "device_id", "key", "value", "ts"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def build_pdf(
    path: Path,
    report_date: str,
    window_label: str,
    alarms: list[dict],
    telemetry_rows: list[dict],
    summary: dict,
) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Delhivery Daily Report {report_date}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontSize=16,
        spaceAfter=6,
    )
    h_style = ParagraphStyle(
        "HeadingCustom",
        parent=styles["Heading2"],
        fontSize=12,
        spaceBefore=10,
        spaceAfter=6,
    )
    body = styles["Normal"]

    story: list[Any] = []
    story.append(Paragraph("Delhivery — Daily Alarm & Telemetry Report", title_style))
    story.append(Paragraph(f"Report date: <b>{report_date}</b> ({REPORT_TZ})", body))
    story.append(Paragraph(f"Window: {window_label}", body))
    story.append(Paragraph(f"Generated at: {now_local().strftime('%Y-%m-%d %H:%M:%S %Z')}", body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Summary", h_style))
    summary_data = [
        ["Metric", "Value"],
        ["Total alarms (window)", str(summary.get("alarm_count", 0))],
        ["Active alarms", str(summary.get("active_count", 0))],
        ["Critical alarms", str(summary.get("critical_count", 0))],
        ["Major alarms", str(summary.get("major_count", 0))],
        ["Devices in report", str(summary.get("device_count", 0))],
        ["Telemetry points", str(summary.get("telemetry_points", 0))],
    ]
    t = Table(summary_data, colWidths=[80 * mm, 60 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t)

    story.append(Paragraph("Alarms", h_style))
    if not alarms:
        story.append(Paragraph("No alarms in this window.", body))
    else:
        alarm_table = [["Created", "Type", "Severity", "Status", "Device", "Details"]]
        for a in alarms[:80]:
            details = a.get("details") or {}
            if isinstance(details, dict):
                details_s = str(details.get("data") or "")[:80]
            else:
                details_s = str(details)[:80]
            status = a.get("status") or (
                ("CLEARED" if a.get("cleared") else "ACTIVE")
                + ("_ACK" if a.get("acknowledged") else "_UNACK")
            )
            alarm_table.append(
                [
                    ms_to_local(a.get("createdTime"))[:19],
                    str(a.get("type") or "")[:28],
                    str(a.get("severity") or ""),
                    str(status)[:14],
                    str(a.get("originatorName") or "")[:22],
                    details_s,
                ]
            )
        at = Table(
            alarm_table,
            colWidths=[32 * mm, 40 * mm, 22 * mm, 28 * mm, 35 * mm, 90 * mm],
            repeatRows=1,
        )
        at.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B91C1C")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(at)
        if len(alarms) > 80:
            story.append(
                Paragraph(f"Showing 80 of {len(alarms)} alarms (full list in CSV).", body)
            )

    story.append(Paragraph("Latest telemetry snapshot", h_style))
    if not telemetry_rows:
        story.append(Paragraph("No telemetry values found.", body))
    else:
        tel_table = [["Device", "Key", "Value", "Timestamp"]]
        for r in telemetry_rows[:100]:
            tel_table.append(
                [
                    str(r.get("device") or "")[:24],
                    str(r.get("key") or ""),
                    str(r.get("value") or "")[:24],
                    str(r.get("ts") or "")[:19],
                ]
            )
        tt = Table(
            tel_table,
            colWidths=[45 * mm, 40 * mm, 40 * mm, 45 * mm],
            repeatRows=1,
        )
        tt.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1D4ED8")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("PADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(tt)

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Generated by ThingsBoard CE + n8n daily report pipeline (branch: report).",
            body,
        )
    )
    doc.build(story)


def generate_report(output_dir: Path | None = None, hours: int = 24) -> dict:
    end = now_local()
    start = end - timedelta(hours=hours)
    report_date = end.strftime("%Y-%m-%d")
    window_label = (
        f"{start.strftime('%Y-%m-%d %H:%M')} → {end.strftime('%Y-%m-%d %H:%M')} {REPORT_TZ}"
    )

    out = output_dir or Path(
        os.environ.get("REPORT_OUTPUT_DIR", "/var/tmp/delhivery-reports")
    ) / report_date
    out.mkdir(parents=True, exist_ok=True)

    sys_token = login_sysadmin()
    token = tenant_token(sys_token)

    devices = fetch_devices(token)
    by_name = {d["name"]: d for d in devices}
    selected = [by_name[n] for n in DEVICE_NAMES if n in by_name]

    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    alarms = fetch_alarms(token, start_ms, end_ms)

    telemetry_rows: list[dict] = []
    for d in selected:
        did = d["id"]["id"]
        latest = fetch_latest_telemetry(token, did, TELEMETRY_KEYS)
        for key, points in (latest or {}).items():
            if not points:
                continue
            p = points[0]
            telemetry_rows.append(
                {
                    "device": d["name"],
                    "device_id": did,
                    "key": key,
                    "value": p.get("value"),
                    "ts": ms_to_local(p.get("ts")),
                }
            )

    def is_active(a: dict) -> bool:
        if "cleared" in a:
            return not a.get("cleared")
        return str(a.get("status") or "").startswith("ACTIVE")

    summary = {
        "tenant": "Delhivery Pvt / Virtuoso NetSoft",
        "report_date": report_date,
        "timezone": REPORT_TZ,
        "window": window_label,
        "hours": hours,
        "alarm_count": len(alarms),
        "active_count": sum(1 for a in alarms if is_active(a)),
        "critical_count": sum(
            1 for a in alarms if str(a.get("severity") or "").upper() == "CRITICAL"
        ),
        "major_count": sum(
            1 for a in alarms if str(a.get("severity") or "").upper() == "MAJOR"
        ),
        "device_count": len(selected),
        "telemetry_points": len(telemetry_rows),
        "devices": [d["name"] for d in selected],
    }

    alarms_csv = out / "alarms.csv"
    telemetry_csv = out / "telemetry_latest.csv"
    pdf_path = out / "report.pdf"
    summary_path = out / "summary.json"

    write_alarms_csv(alarms_csv, alarms)
    write_telemetry_csv(telemetry_csv, telemetry_rows)
    build_pdf(pdf_path, report_date, window_label, alarms, telemetry_rows, summary)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    result = {
        "ok": True,
        "report_date": report_date,
        "output_dir": str(out),
        "files": {
            "alarms_csv": str(alarms_csv),
            "telemetry_csv": str(telemetry_csv),
            "pdf": str(pdf_path),
            "summary_json": str(summary_path),
        },
        "summary": summary,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Delhivery daily TB report")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    parser.add_argument("--output-dir", type=str, default=None)
    args = parser.parse_args(argv)
    try:
        result = generate_report(
            output_dir=Path(args.output_dir) if args.output_dir else None,
            hours=args.hours,
        )
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
