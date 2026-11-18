"""CMMS API on the in-memory ThingsBoard, for the widget end-to-end test (period_reports/tests/test_maintenance_planner.js).

  python3 -m cmms.tests.e2e_server     -> prints one JSON line {port, ids, users}, then serves until stdin closes

/cmms/v1/... is the real API (cmms/api.py); /__test/... lets the test inspect and change the fake ThingsBoard.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cmms.api import Api
from cmms.tests.fake_tb import FakeClient, site

tb, ids, people, customers = site()
api = Api(lambda: FakeClient(tb))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, headers, body):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _test(self):
        if self.path == "/__test/db":
            return self._send(200, {"Content-Type": "application/json"}, json.dumps(tb.dump(), default=str).encode())
        p = json.loads(self._body() or b"{}")
        if self.path == "/__test/attr":          # {id, key, value}; value null deletes the attribute
            if p.get("value") is None:
                tb.a(p["id"]).pop(p["key"], None)
            else:
                tb.a(p["id"])[p["key"]] = p["value"]
        elif self.path == "/__test/hide":        # an asset created by someone else that the queries do not see yet
            tb.asset(p["name"], p["type"])
            tb.hidden_names.add(p["name"])
        api._tokens.clear()
        return self._send(200, {"Content-Type": "application/json"}, b"{}")

    def _cmms(self, method):
        cache = {}

        def read(limit):
            if "b" not in cache:
                cache["b"] = self._body()
            return cache["b"]
        self._send(*api.handle(method, self.path, self.headers, read))

    def do_GET(self):
        return self._test() if self.path.startswith("/__test/") else self._cmms("GET")

    def do_POST(self):
        return self._test() if self.path.startswith("/__test/") else self._cmms("POST")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(json.dumps({"port": server.server_address[1], "ids": ids,
                      "settings_id": tb.by_name("Maintenance Settings"), "library_id": tb.by_name("Maintenance Document Library")}), flush=True)
    sys.stdin.read()          # the test closes stdin when it is done
