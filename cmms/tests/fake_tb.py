"""In-memory ThingsBoard for the CMMS tests. It behaves like the real one where it matters: null attribute values are
rejected (HTTP 500), duplicate asset names are rejected (HTTP 400), entity-query values come back as strings, users are
identified by their JWT, customer devices are only the ones assigned to the customer."""
import copy
import json
import os
import re
import uuid
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = json.load(open(os.path.join(HERE, "..", "settings_seed.json")))
SEED.pop("_note", None)
PM_SEED = json.load(open(os.path.join(HERE, "..", "..", "predictive_maintenance", "pm_seed.json")))
TENANT = "tenant-1"


class Response:
    def __init__(self, status, body=None, content=None, ctype="application/json"):
        self.status_code = status
        if content is not None:
            self.content, self.text = content, "<binary>"
        else:
            self.text = "" if body is None else (body if isinstance(body, str) else json.dumps(body))
            self.content = self.text.encode()
        self.headers = {"Content-Type": ctype}

    def json(self):
        return json.loads(self.text)


def uid():
    return str(uuid.uuid4())


class FakeTB:
    def __init__(self):
        self.assets, self.attrs, self.relations, self.ts, self.resources = {}, {}, [], [], {}
        self.devices, self.users, self.tokens, self.customers, self.alarms = {}, {}, {}, {}, []
        self.hidden_names = set()
        self.calls = []

    # ------------------------------------------------------------------ seeding
    def device(self, name, dtype, keys, customer=None, meter=None):
        did = uid()
        self.devices[did] = {"name": name, "type": dtype, "keys": keys, "customer": customer, "meter": meter or []}
        return did

    def asset(self, name, atype, attrs=None):
        aid = uid()
        self.assets[aid] = {"name": name, "type": atype}
        self.attrs[aid] = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in (attrs or {}).items()}
        return aid

    def user(self, token, first, authority, customer=None):
        u = {"id": {"id": uid()}, "email": f"{first.lower()}@site", "firstName": first, "lastName": "", "authority": authority,
             "tenantId": {"id": TENANT}, "customerId": {"id": customer or "13814000-1dd2-11b2-8080-808080808080"}}
        self.users[u["id"]["id"]] = u
        self.tokens[token] = u
        return u

    # ------------------------------------------------------------------ helpers
    def a(self, eid):
        return self.attrs.setdefault(eid, {})

    def j(self, eid, key):
        v = self.a(eid).get(key)
        return json.loads(v) if isinstance(v, str) and v[:1] in "{[" else v

    def by_name(self, name):
        return next((k for k, v in self.assets.items() if v["name"] == name), None)

    def page(self, rows):
        return {"data": rows, "hasNext": False, "totalElements": len(rows)}

    # ------------------------------------------------------------------ requests-like API
    def request(self, method, url, headers=None, params=None, json=None, data=None, files=None, timeout=None):
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        q.update({k: str(v) for k, v in (params or {}).items()})
        token = ((headers or {}).get("X-Authorization") or "")[7:]
        self.calls.append((method, u.path))
        try:
            return self._handle(method, u.path, q, token, json, data, files)
        except KeyError as exc:
            return Response(404, {"message": f"not found {exc}"})

    def _handle(self, method, path, q, token, body, data, files):
        user = self.tokens.get(token)
        if user is None:
            return Response(401, {"message": "Authentication failed"})
        if method == "GET" and path == "/api/auth/user":
            return Response(200, user)
        if user["authority"] != "TENANT_ADMIN":
            return Response(403, {"message": "You don't have permission to perform this operation!"})
        m = re.fullmatch(r"/api/plugins/telemetry/(DEVICE|ASSET)/([^/]+)/(.*)", path)
        if m:
            eid, rest = m.group(2), m.group(3)
            if rest == "values/attributes/SERVER_SCOPE":
                a = self.a(eid)
                return Response(200, [{"key": k, "value": a[k]} for k in q["keys"].split(",") if k in a])
            if rest == "attributes/SERVER_SCOPE":
                if any(v is None for v in body.values()):
                    return Response(500, {"message": "Can't parse value: null"})
                self.a(eid).update(copy.deepcopy(body))
                return Response(200)
            if rest == "keys/timeseries":
                return Response(200, self.devices[eid]["keys"])
            if rest == "values/timeseries":
                return Response(200, {q["keys"]: self.devices[eid]["meter"]} if self.devices[eid]["meter"] else {})
            if rest == "timeseries/ANY":
                for p in body:
                    self.ts.append({"id": eid, "ts": p["ts"], "values": p["values"]})
                return Response(200)
        if method == "POST" and path == "/api/entitiesQuery/find":
            f = body["entityFilter"]
            rows = []
            for aid, a in sorted(self.assets.items(), key=lambda x: x[1]["name"]):
                if a["type"] not in f["assetTypes"] or not a["name"].startswith(f.get("assetNameFilter") or "") or a["name"] in self.hidden_names:
                    continue
                vals = {k["key"]: {"ts": 1, "value": "" if self.a(aid).get(k["key"]) is None else
                                   (str(self.a(aid)[k["key"]]).lower() if isinstance(self.a(aid)[k["key"]], bool) else str(self.a(aid)[k["key"]]))}
                        for k in body["latestValues"]}
                rows.append({"entityId": {"id": aid}, "latest": {"ENTITY_FIELD": {"name": {"value": a["name"]}}, "SERVER_ATTRIBUTE": vals}})
            return Response(200, self.page(rows))
        if method == "POST" and path == "/api/asset":
            if any(a["name"] == body["name"] for a in self.assets.values()):
                return Response(400, {"message": "Asset with such name already exists!"})
            aid = uid()
            self.assets[aid] = {"name": body["name"], "type": body["type"], "label": body.get("label")}
            return Response(200, {"id": {"id": aid}, "name": body["name"], "type": body["type"]})
        m = re.fullmatch(r"/api/asset/([^/]+)", path)
        if method == "GET" and m:
            a = self.assets[m.group(1)]
            return Response(200, {"id": {"id": m.group(1)}, "name": a["name"], "type": a["type"]})
        if method == "DELETE" and m:
            self.assets.pop(m.group(1), None)
            self.attrs.pop(m.group(1), None)
            self.relations = [r for r in self.relations if (r.get("to") or {}).get("id") != m.group(1)]
            return Response(200)
        if method == "GET" and path == "/api/tenant/assets":
            aid = self.by_name(q["assetName"])
            if not aid:
                return Response(404, {"message": "Requested item wasn't found!"})
            return Response(200, {"id": {"id": aid}, "name": self.assets[aid]["name"]})
        if method == "POST" and path == "/api/relation":
            self.relations.append(body)
            return Response(200)
        if method == "GET" and path == "/api/tenant/devices":
            return Response(200, self.page([self._dev(k) for k, d in self.devices.items() if d["type"] == q.get("type")]))
        m = re.fullmatch(r"/api/customer/([^/]+)/devices", path)
        if method == "GET" and m:
            return Response(200, self.page([self._dev(k) for k, d in self.devices.items()
                                            if d["type"] == q.get("type") and d["customer"] == m.group(1)]))
        if method == "POST" and path == "/api/resource/upload":
            rid = uid()
            name, content, ctype = files["file"]
            self.resources[rid] = {"title": data["title"], "file": name, "data": content, "type": ctype}
            return Response(200, {"id": {"id": rid}, "title": data["title"]})
        m = re.fullmatch(r"/api/resource/([^/]+)(/download)?", path)
        if m and method == "GET" and m.group(2):
            r = self.resources[m.group(1)]
            return Response(200, content=r["data"], ctype=r["type"])
        if m and method == "DELETE":
            self.resources.pop(m.group(1))
            return Response(200)
        if method == "GET" and path == "/api/users":
            return Response(200, self.page(list(self.users.values())))
        if method == "GET" and path == "/api/customers":
            return Response(200, self.page([{"id": {"id": k}, "title": v} for k, v in self.customers.items()]))
        if method == "GET" and path == "/api/deviceProfileInfos":
            return Response(200, self.page([{"name": n} for n in sorted({d["type"] for d in self.devices.values()})]))
        if method == "GET" and path == "/api/v2/alarms":
            return Response(200, self.page(self.alarms))
        return Response(404, {"message": f"fake: no route {method} {path}"})

    def _dev(self, k):
        return {"id": {"id": k}, "name": self.devices[k]["name"], "type": self.devices[k]["type"]}

    # ------------------------------------------------------------------ inspection
    def dump(self):
        return {"assets": self.assets, "attrs": self.attrs, "ts": self.ts, "relations": self.relations,
                "resources": {k: {"title": v["title"], "file": v["file"]} for k, v in self.resources.items()},
                "devices": self.devices, "users": self.users}


class FakeClient:
    def __init__(self, tb, token="svc"):
        self.base_url, self.session, self._headers = "http://tb", tb, {"X-Authorization": f"Bearer {token}"}


def site():
    """The test site: two customers, equipment of configured and unconfigured profiles, users of every role."""
    tb = FakeTB()
    c1, c2 = uid(), uid()
    tb.customers = {c1: "Developer", c2: "Other client"}
    dg_pm = {"kind": "DG", "engine": PM_SEED["engine"], "limits": copy.deepcopy(PM_SEED["kinds"]["DG"])}
    ids = {
        "dg1": tb.device("DG SET1", "woodward_kg1500", ["run_hours", "battery_voltage"], c1,
                         [{"ts": 3, "value": "error"}, {"ts": 2, "value": "32767"}, {"ts": 1, "value": "166.1"}]),
        "ro": tb.device("RO Plant System", "RO System Profile", ["tds_ppm"], c1),
        "lt": tb.device("LT Panel 2", "LT Panels Profile", ["voltage"], c2),
        "x9": tb.device("Unrelated meter", "Some Other Profile", ["run_hours"], c1),
    }
    tb.a(ids["dg1"])["pm_config"] = json.dumps(dg_pm)
    tb.asset("Maintenance Document Library", "Maintenance Library")
    tb.user("svc", "Service", "TENANT_ADMIN")
    people = {"admin": tb.user("tok-admin", "Admin", "TENANT_ADMIN")}
    roles = {}
    for token, first, role, cust in [("tok-sup", "Sunil", "supervisor", c1), ("tok-tech", "Ravi", "technician", c1),
                                     ("tok-tech2", "Mohan", "technician", c1), ("tok-req", "Priya", "requester", c1),
                                     ("tok-view", "Vikas", "viewer", c1), ("tok-none", "Nobody", None, c1),
                                     ("tok-c2", "Other", "supervisor", c2)]:
        u = tb.user(token, first, "CUSTOMER_USER", cust)
        people[token[4:]] = u
        if role:
            roles[u["id"]["id"]] = {"role": role, "name": first, "email": u["email"], "customer_id": cust}
    tb.asset("Maintenance Settings", "Maintenance Settings",
             {"cmms_settings": SEED, "cmms_settings_rev": 1, "pm_templates": PM_SEED, "cmms_roles": roles, "cmms_roles_rev": 1})
    return tb, ids, people, (c1, c2)
