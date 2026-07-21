from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_latest_report_summary(reports_dir: str) -> dict[str, Any] | None:
    root = Path(reports_dir)
    if not root.exists():
        return None
    dated = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)
    for day in dated[:5]:
        summary = day / "summary.json"
        if summary.exists():
            try:
                data = json.loads(summary.read_text(encoding="utf-8"))
                data["_path"] = str(summary)
                data["_date"] = day.name
                return data
            except Exception:
                continue
    return None


def format_report_context(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "No daily report summary available."
    date = summary.get("_date") or "unknown"
    devices = summary.get("devices") or summary.get("deviceSummaries") or []
    lines = [f"Daily report date: {date}"]
    if isinstance(devices, list):
        for d in devices[:12]:
            if isinstance(d, dict):
                name = d.get("name") or d.get("deviceName") or "device"
                lines.append(f"- {name}: {json.dumps(d, ensure_ascii=True)[:240]}")
            else:
                lines.append(f"- {d}")
    else:
        lines.append(json.dumps(summary, ensure_ascii=True)[:1200])
    return "\n".join(lines)
