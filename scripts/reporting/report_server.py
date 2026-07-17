#!/usr/bin/env python3
"""
Minimal HTTP API for n8n to trigger Delhivery daily reports.

Endpoints:
  GET  /health
  POST /v1/delhivery/daily-report   body: {"hours": 24}
  GET  /v1/delhivery/daily-report?hours=24
  GET  /v1/delhivery/files/<date>/<filename>
"""

from __future__ import annotations

import json
import mimetypes
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from delhivery_daily_report import generate_report

HOST = os.environ.get("REPORT_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("REPORT_API_PORT", "5060"))
OUTPUT_ROOT = Path(os.environ.get("REPORT_OUTPUT_DIR", "/var/tmp/delhivery-reports"))


class Handler(BaseHTTPRequestHandler):
    server_version = "DelhiveryReportAPI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[report-api] {self.address_string()} - {fmt % args}", flush=True)

    def _send(self, code: int, body: dict | bytes, content_type: str = "application/json"):
        if isinstance(body, dict):
            raw = json.dumps(body).encode()
            content_type = "application/json"
        else:
            raw = body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/health":
            self._send(200, {"ok": True, "service": "delhivery-daily-report"})
            return

        if path in ("/v1/delhivery/daily-report", "/v1/delhivery/daily-report/"):
            hours = int((qs.get("hours") or ["24"])[0])
            self._run_report(hours)
            return

        if path.startswith("/v1/delhivery/files/"):
            # /v1/delhivery/files/YYYY-MM-DD/filename
            parts = path.strip("/").split("/")
            # v1 delhivery files date filename
            if len(parts) != 5:
                self._send(400, {"ok": False, "error": "Expected /v1/delhivery/files/<date>/<file>"})
                return
            date, filename = parts[3], parts[4]
            if ".." in date or ".." in filename or "/" in filename:
                self._send(400, {"ok": False, "error": "Invalid path"})
                return
            file_path = OUTPUT_ROOT / date / filename
            if not file_path.is_file():
                self._send(404, {"ok": False, "error": f"File not found: {date}/{filename}"})
                return
            ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            self._send(200, file_path.read_bytes(), content_type=ctype)
            return

        self._send(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": "Invalid JSON"})
            return

        if path in ("/v1/delhivery/daily-report", "/v1/delhivery/daily-report/"):
            hours = int(body.get("hours") or 24)
            self._run_report(hours)
            return

        self._send(404, {"ok": False, "error": "Not found"})

    def _public_base(self) -> str:
        # Prefer explicit public base (Docker → host). Fall back to request Host.
        explicit = os.environ.get("REPORT_PUBLIC_BASE", "").rstrip("/")
        if explicit:
            return explicit
        host = self.headers.get("Host") or f"127.0.0.1:{PORT}"
        return f"http://{host}"

    def _run_report(self, hours: int):
        try:
            result = generate_report(hours=hours)
            # Add download URLs for n8n
            date = result["report_date"]
            base = f"{self._public_base()}/v1/delhivery/files/{date}"
            result["download_urls"] = {
                "alarms_csv": f"{base}/alarms.csv",
                "telemetry_csv": f"{base}/telemetry_latest.csv",
                "pdf": f"{base}/report.pdf",
                "summary_json": f"{base}/summary.json",
            }
            self._send(200, result)
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"ok": False, "error": str(e)})


def main():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Delhivery report API listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
