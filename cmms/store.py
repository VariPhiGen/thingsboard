"""ThingsBoard persistence for the CMMS.

Maintenance plans and work orders are ThingsBoard assets (types "Maintenance Plan" / "Work Order"), related to their
equipment device with relation type "Maintenance". Fields are server attributes (plan_* / wo_*), so they can be queried
and filtered by ThingsBoard itself and every change is in the ThingsBoard audit log. The asset name is the record
number (PL-0001, WO-2026-00001); ThingsBoard enforces unique asset names per tenant, which makes numbering safe when the
scheduler and dashboard users create records at the same time.
"""
import json
import logging
import re
import time

log = logging.getLogger(__name__)

# Data-model identifiers (schema names, not business values)
PLAN_TYPE, WO_TYPE, LIBRARY_NAME, LIBRARY_TYPE = "Maintenance Plan", "Work Order", "Maintenance Document Library", "Maintenance Library"
SETTINGS_NAME, SETTINGS_TYPE, SETTINGS_KEY = "Maintenance Settings", "Maintenance Settings", "cmms_settings"
SETTINGS_KEYS = ["cmms_settings", "cmms_settings_rev", "pm_templates", "cmms_roles", "cmms_roles_rev"]
RELATION = "Maintenance"

WO_KEYS = ["wo_title", "wo_type", "wo_priority", "wo_status", "wo_source", "wo_plan_id", "wo_alarm_id", "wo_equipment_id",
           "wo_equipment_name", "wo_due_date", "wo_due_rh", "wo_interval_rh", "wo_assignee", "wo_assignee_id", "wo_created_ts",
           "wo_completed_ts", "wo_closed_ts", "wo_rev", "wo_overdue_alerted", "wo_detail"]
PLAN_KEYS = ["plan_title", "plan_type", "plan_priority", "plan_strategy", "plan_interval_days", "plan_interval_rh",
             "plan_lead_days", "plan_next_due_date", "plan_next_due_rh", "plan_active", "plan_equipment_id",
             "plan_equipment_name", "plan_rev", "plan_detail"]


class StoreError(RuntimeError):
    pass


class ConflictError(StoreError):
    """The record was changed by someone else since it was read (rev mismatch)."""


def _value(v):
    """Attribute value as returned by the entity query (always a string) -> python value."""
    if v is None:
        return None
    if isinstance(v, (int, float, bool, dict, list)):
        return v
    s = str(v)
    if s in ("", "null"):
        return None
    if s in ("true", "false"):
        return s == "true"
    if s[:1] in "{[":
        try:
            return json.loads(s)
        except ValueError:
            return s
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s) if "." in s else int(s)
    return s


def _strip(prefix, row):
    return {k[len(prefix):]: v for k, v in row.items() if k.startswith(prefix)}


class Store:
    def __init__(self, client):
        self.c = client

    # ------------------------------------------------------------------ http
    def _raw(self, method, path, **kw):
        res = self.c.session.request(method, f"{self.c.base_url}{path}", headers=self.c._headers, timeout=60, **kw)
        if res.status_code >= 400:
            raise StoreError(f"{method} {path}: HTTP {res.status_code} {res.text[:300]}")
        return res

    def _req(self, method, path, **kw):
        res = self._raw(method, path, **kw)
        return res.json() if res.text else None

    def _pages(self, path, params=None):
        out, page = [], 0
        while True:
            res = self._req("GET", path, params=dict(params or {}, pageSize=500, page=page))
            out += res.get("data", [])
            if not res.get("hasNext"):
                return out
            page += 1

    def query_assets(self, asset_type, keys, name_prefix=""):
        out, page = [], 0
        while True:
            body = {"entityFilter": {"type": "assetType", "assetTypes": [asset_type], "assetNameFilter": name_prefix},
                    "pageLink": {"page": page, "pageSize": 500,
                                 "sortOrder": {"key": {"type": "ENTITY_FIELD", "key": "name"}, "direction": "ASC"}},
                    "entityFields": [{"type": "ENTITY_FIELD", "key": "name"}],
                    "latestValues": [{"type": "SERVER_ATTRIBUTE", "key": k} for k in keys]}
            res = self._req("POST", "/api/entitiesQuery/find", json=body)
            for row in res.get("data", []):
                latest = row.get("latest", {})
                rec = {"id": row["entityId"]["id"], "name": latest.get("ENTITY_FIELD", {}).get("name", {}).get("value")}
                for k, v in latest.get("SERVER_ATTRIBUTE", {}).items():
                    rec[k] = _value(v.get("value"))
                out.append(rec)
            if not res.get("hasNext"):
                return out
            page += 1

    def save_attrs(self, entity_type, entity_id, values):
        # ThingsBoard rejects the whole request (HTTP 500) for a null value; "" clears a field and reads back as None
        body = {k: ("" if v is None else json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in values.items()}
        self._req("POST", f"/api/plugins/telemetry/{entity_type}/{entity_id}/attributes/SERVER_SCOPE", json=body)

    def attrs(self, entity_type, entity_id, keys):
        res = self._req("GET", f"/api/plugins/telemetry/{entity_type}/{entity_id}/values/attributes/SERVER_SCOPE",
                        params={"keys": ",".join(keys)}) or []
        return {a["key"]: _value(a["value"]) for a in res}

    # ------------------------------------------------------------------ records
    def work_orders(self):
        return [dict(_strip("wo_", r), id=r["id"], number=r["name"]) for r in self.query_assets(WO_TYPE, WO_KEYS)]

    def plans(self):
        return [dict(_strip("plan_", r), id=r["id"], number=r["name"]) for r in self.query_assets(PLAN_TYPE, PLAN_KEYS)]

    def _create_numbered(self, asset_type, prefix, width, label):
        existing = self.query_assets(asset_type, [], name_prefix=prefix)
        nums = [int(m.group(1)) for m in (re.fullmatch(re.escape(prefix) + r"(\d+)", r["name"] or "") for r in existing) if m]
        n = max(nums or [0]) + 1
        for _ in range(25):
            name = f"{prefix}{n:0{width}d}"
            try:
                return self._req("POST", "/api/asset", json={"name": name, "type": asset_type, "label": label[:255]})
            except StoreError as exc:
                if "already exists" not in str(exc).lower() and "400" not in str(exc):
                    raise
                n += 1
        raise StoreError(f"Could not allocate a {asset_type} number after 25 attempts")

    def _record(self, aid, asset_type, prefix, keys):
        """One plan / work order by asset id (None when it does not exist or is another kind of asset)."""
        if not aid or not re.fullmatch(r"[0-9a-fA-F-]{36}", str(aid)):
            return None
        try:
            asset = self._req("GET", f"/api/asset/{aid}")
        except StoreError as exc:
            if "HTTP 404" in str(exc) or "HTTP 400" in str(exc):
                return None
            raise
        if not asset or asset.get("type") != asset_type:
            return None
        values = self.attrs("ASSET", aid, keys)
        return dict({k[len(prefix):]: v for k, v in values.items()}, id=aid, number=asset["name"])

    def work_order(self, aid):
        return self._record(aid, WO_TYPE, "wo_", WO_KEYS)

    def delete_work_order(self, aid):
        """Remove a work order for good (its asset and relations; ThingsBoard keeps the audit-log entry)."""
        self._req("DELETE", f"/api/asset/{aid}")

    def plan(self, aid):
        return self._record(aid, PLAN_TYPE, "plan_", PLAN_KEYS)

    def relate(self, device_id, asset_id):
        self._req("POST", "/api/relation", json={"from": {"entityType": "DEVICE", "id": device_id},
                                                 "to": {"entityType": "ASSET", "id": asset_id},
                                                 "type": RELATION, "typeGroup": "COMMON"})

    def create_work_order(self, fields, detail, year):
        asset = self._create_numbered(WO_TYPE, f"WO-{year}-", 5, fields["title"])
        aid = asset["id"]["id"]
        values = {"wo_" + k: v for k, v in fields.items()}
        values.update(wo_rev=1, wo_overdue_alerted=False, wo_detail=detail)
        self.save_attrs("ASSET", aid, values)
        self.relate(fields["equipment_id"], aid)
        log.info("Created %s %s (%s)", asset["name"], fields["title"], fields.get("source"))
        return asset["name"], aid

    def update_work_order(self, wo, values):
        """values: wo_* keys; bumps wo_rev after checking nobody changed the record since it was read."""
        self._guarded(wo, "wo_", values)

    def _guarded(self, rec, prefix, values):
        cur = self.attrs("ASSET", rec["id"], [prefix + "rev"]).get(prefix + "rev")
        if cur is not None and rec.get("rev") is not None and int(cur) != int(rec["rev"]):
            raise ConflictError(f"{rec['number']} was changed by someone else meanwhile; reload and try again")
        self.save_attrs("ASSET", rec["id"], dict(values, **{prefix + "rev": int(cur or 0) + 1}))

    def create_plan(self, values, title):
        asset = self._create_numbered(PLAN_TYPE, "PL-", 4, title)
        aid = asset["id"]["id"]
        self.save_attrs("ASSET", aid, dict(values, plan_rev=1))
        self.relate(values["plan_equipment_id"], aid)
        log.info("Created %s %s", asset["name"], title)
        return asset["name"], aid

    def update_plan(self, plan, values):
        self._guarded(plan, "plan_", values)

    def save_record(self, device_id, ts, values):
        self._req("POST", f"/api/plugins/telemetry/DEVICE/{device_id}/timeseries/ANY", json=[{"ts": ts, "values": values}])

    # ------------------------------------------------------------------ files (ThingsBoard GENERAL resources)
    def upload_resource(self, filename, data, content_type, title):
        res = self._req("POST", "/api/resource/upload", data={"resourceType": "GENERAL", "title": title[:255]},
                        files={"file": (filename, data, content_type or "application/octet-stream")})
        return res["id"]["id"]

    def download_resource(self, rid):
        res = self._raw("GET", f"/api/resource/{rid}/download")
        return res.content, res.headers.get("Content-Type") or "application/octet-stream"

    def delete_resource(self, rid):
        try:
            self._req("DELETE", f"/api/resource/{rid}")
        except StoreError as exc:
            if "HTTP 404" not in str(exc):
                raise

    # ------------------------------------------------------------------ configuration
    def _asset_id(self, name):
        try:
            res = self._req("GET", "/api/tenant/assets", params={"assetName": name})
        except StoreError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
        return res["id"]["id"] if res else None

    def settings(self):
        """Raw cmms_settings dict from the 'Maintenance Settings' asset, or None when it is not configured."""
        sid = self._asset_id(SETTINGS_NAME)
        return self.attrs("ASSET", sid, [SETTINGS_KEY]).get(SETTINGS_KEY) if sid else None

    def settings_asset(self):
        """(asset id, {cmms_settings, cmms_settings_rev, pm_templates, cmms_roles, cmms_roles_rev}) or (None, {})."""
        sid = self._asset_id(SETTINGS_NAME)
        return (sid, self.attrs("ASSET", sid, SETTINGS_KEYS)) if sid else (None, {})

    def library(self):
        return self._asset_id(LIBRARY_NAME)

    # ------------------------------------------------------------------ equipment data
    def equipment(self, settings, customer_id=None):
        """Devices of the device profiles configured in the settings (only those assigned to customer_id when given)."""
        path = f"/api/customer/{customer_id}/devices" if customer_id else "/api/tenant/devices"
        out = []
        for profile in settings.raw["equipment_profiles"]:
            out += [{"id": d["id"]["id"], "name": d["name"], "type": d["type"]} for d in self._pages(path, {"type": profile})]
        return out

    def timeseries_keys(self, device_id):
        return self._req("GET", f"/api/plugins/telemetry/DEVICE/{device_id}/keys/timeseries") or []

    def users(self):
        """All users of the tenant (tenant administrators and customer users)."""
        return self._pages("/api/users")

    def customers(self):
        return {c["id"]["id"]: c.get("title") or c.get("name") for c in self._pages("/api/customers")}

    def device_profiles(self):
        return [p["name"] for p in self._pages("/api/deviceProfileInfos", {"sortProperty": "name", "sortOrder": "ASC"})]

    def meter_reading(self, device_id, settings):
        """Latest valid reading of the configured meter key (e.g. run hours) in the last 3 days, or None.
        Controllers sometimes send text ('error') or 'not available' codes; those are outside the configured valid range."""
        now = int(time.time() * 1000)
        res = self._req("GET", f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
                        params={"keys": settings.meter_key, "startTs": now - 3 * 86400000, "endTs": now, "limit": 200,
                                "agg": "NONE", "orderBy": "DESC"}) or {}
        for p in res.get(settings.meter_key, []):
            try:
                v = float(p["value"])
            except (TypeError, ValueError):
                continue
            if settings.valid_meter(v):
                return round(v, 1)
        return None

    def active_alarms(self):
        out, page = [], 0
        while True:
            res = self._req("GET", "/api/v2/alarms", params={"pageSize": 500, "page": page, "statusList": "ACTIVE"})
            out += res.get("data", [])
            if not res.get("hasNext"):
                return out
            page += 1

    def documents(self, equipment):
        out = []
        for e in equipment:
            for d in self.attrs("DEVICE", e["id"], ["maint_docs"]).get("maint_docs") or []:
                out.append(dict(d, owner=e["name"]))
        lib = self.library()
        if lib:
            for d in self.attrs("ASSET", lib, ["maint_docs"]).get("maint_docs") or []:
                out.append(dict(d, owner="All equipment"))
        return out
