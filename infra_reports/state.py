"""Record of the last successfully emailed report, read by the daily health check."""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .config import REPORT_TZ

STATE_PATH = Path(__file__).resolve().parent.parent / ".infra_report_state" / "last_success.json"


def record_success(report_day, recipients, filenames, path=STATE_PATH):
    """Atomically store which report day was emailed, when and to whom."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "report_day": report_day.strftime("%Y-%m-%d"),
        "sent_at": datetime.now(REPORT_TZ).isoformat(timespec="seconds"),
        "recipients": sorted(recipients),
        "files": list(filenames),
    }
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".last_success.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return record


def read_last_success(path=STATE_PATH):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
