#!/usr/bin/env python3
"""Standard library HTTP server for n8n report integration."""
import json
import logging
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Ensure thingsboard directory is on path
TB_DIR = os.path.dirname(os.path.abspath(__file__))
if TB_DIR not in sys.path:
    sys.path.insert(0, TB_DIR)

import generate_separate_pdfs_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("report_api")

HOST = os.environ.get("REPORT_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("REPORT_API_PORT", "5055"))


class ReportAPIHandler(BaseHTTPRequestHandler):
    server_version = "VirtuosoReportAPI/1.0"

    def log_message(self, fmt, *args):
        log.info(f"{self.address_string()} - {fmt % args}")

    def _send_json(self, status_code: int, data: dict):
        raw = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
        if path == "/health":
            self._send_json(200, {"ok": True, "service": "virtuoso-report-api", "version": "1.0.0"})
            return
        self._send_json(404, {"ok": False, "error": f"Path not found: {path}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path in (
            "/v1/generate-infrastructure-separate-pdfs-report",
            "/generate-infrastructure-separate-pdfs-report",
            "/api/v1/generate-infrastructure-separate-pdfs-report",
        ):
            content_length = int(self.headers.get("Content-Length") or 0)
            body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                payload = json.loads(body_bytes.decode("utf-8") or "{}")
            except Exception:
                payload = {}

            report_date = payload.get("report_date")
            recipients = payload.get("recipients")
            send_email = payload.get("send_email", True)

            try:
                summary = generate_separate_pdfs_report.fetch_master_devices_summary(report_date)
                reports = generate_separate_pdfs_report.generate_all_separate_pdfs(summary)

                email_sent = False
                if send_email:
                    email_sent = generate_separate_pdfs_report.send_email_with_separate_pdfs(reports, recipients)

                self._send_json(200, {
                    "ok": True,
                    "email_sent": email_sent,
                    "generated_pdfs_count": len([r for r in reports if r.get('pdf_bytes')]),
                    "pdf_files": [
                        {
                            "name": r["name"],
                            "filename": r["filename"],
                            "pdf_size_bytes": len(r["pdf_bytes"]) if r.get("pdf_bytes") else 0
                        }
                        for r in reports
                    ]
                })
            except Exception as exc:
                log.error("Report generation failed: %s", exc, exc_info=True)
                self._send_json(500, {"ok": False, "error": str(exc)})
            return

        self._send_json(404, {"ok": False, "error": f"Path not found: {path}"})


def main():
    server = ThreadingHTTPServer((HOST, PORT), ReportAPIHandler)
    log.info("Virtuoso Report API server listening on http://%s:%d", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
