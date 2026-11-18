"""CMMS commands of the dashboard, executed on the server with the service account on behalf of a verified user.

The dashboard widget never writes to ThingsBoard itself: every change is a command here, checked against the user's
role (roles.py), the equipment the user may see (customer users: devices assigned to their customer), the work-order
lifecycle and segregation of duties (model.py), the configuration (cmms_settings) and the record revision. History
entries carry the verified user, never a name sent by the browser. Work orders, plans, settings and roles are tenant
assets that are not assigned to customers, so customer users cannot change them through the ThingsBoard API either.
"""
import copy
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from . import model as m
from . import roles as R
from .scheduler import wo_from_plan
from .store import ConflictError, StoreError

log = logging.getLogger("cmms.service")

# Field length limits (input hygiene, not business values)
TITLE, TEXT, LONG_TEXT, NAME, NOTE, SHORT = 120, 1000, 1500, 80, 500, 40
MAX_LIST = 100
# one write at a time in this process: read-check-write sequences of different users cannot interleave
WRITE_LOCK = threading.Lock()


class Invalid(ValueError):
    """The request is not valid (HTTP 400)."""


class NotFound(LookupError):
    """The record does not exist or is not visible to the user (HTTP 404)."""


@dataclass
class User:
    id: str
    email: str
    name: str
    authority: str
    customer_id: str
    role: str

    @property
    def tenant_admin(self):
        return self.authority == "TENANT_ADMIN"


def now_ms():
    return int(time.time() * 1000)


def user_name(u):
    return " ".join(x for x in (u.get("firstName"), u.get("lastName")) if x) or u.get("email") or ""


# ----------------------------------------------------------------------------- input validation
def text(p, key, maxlen, required=False, label=None):
    v = p.get(key)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise Invalid(f"{label or key.replace('_', ' ').capitalize()} is required")
    if len(v) > maxlen:
        raise Invalid(f"{label or key} is longer than {maxlen} characters")
    return v


def number(p, key, minimum=None, required=False, label=None, integer=False):
    v = p.get(key)
    lab = label or key.replace("_", " ")
    if v is None or v == "":
        if required:
            raise Invalid(f"{lab.capitalize()} is required")
        return None
    if isinstance(v, bool):
        raise Invalid(f"{lab.capitalize()} must be a number")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise Invalid(f"{lab.capitalize()} must be a number")
    if f != f or f in (float("inf"), float("-inf")):
        raise Invalid(f"{lab.capitalize()} must be a number")
    if integer and f != int(f):
        raise Invalid(f"{lab.capitalize()} must be a whole number")
    if minimum is not None and f < minimum:
        raise Invalid(f"{lab.capitalize()} must be at least {minimum}")
    return int(f) if integer else f


def day(p, key, required=False, label=None):
    v = text(p, key, 10, required, label)
    if not v:
        return ""
    try:
        return datetime.strptime(v, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise Invalid(f"{label or key} must be a date (YYYY-MM-DD)")


def lines(p, key, maxlen=200):
    v = p.get(key) or []
    if not isinstance(v, list) or len(v) > MAX_LIST:
        raise Invalid(f"{key} must be a list of at most {MAX_LIST} entries")
    out = [str(x).strip() for x in v if str(x).strip()]
    if any(len(x) > maxlen for x in out):
        raise Invalid(f"An entry of {key} is longer than {maxlen} characters")
    return out


def _ids(v, label):
    if not isinstance(v or [], list) or len(v or []) > MAX_LIST:
        raise Invalid(f"{label} must be a list")
    return [str(x) for x in (v or [])]


# ----------------------------------------------------------------------------- uploads
class Uploads:
    """Files uploaded by a user and not yet attached to a record. An upload can only be used by the user who uploaded
    it, for the purpose it was uploaded for; files never used are deleted after max_age_s."""

    def __init__(self, max_age_s):
        self.max_age_s = max_age_s
        self._items, self._lock = {}, threading.Lock()

    def add(self, rid, user, purpose, meta):
        with self._lock:
            self._items[rid] = {"user": user.id, "purpose": purpose, "meta": meta, "ts": time.time()}

    def check(self, ids, user, purpose):
        with self._lock:
            for rid in ids:
                it = self._items.get(rid)
                if not it or it["user"] != user.id or it["purpose"] != purpose:
                    raise Invalid("An attached file was not uploaded in this session; attach it again")

    def take(self, ids, user, purpose):
        self.check(ids, user, purpose)
        with self._lock:
            return [dict(self._items.pop(rid)["meta"]) for rid in ids]

    def expired(self):
        cut = time.time() - self.max_age_s
        with self._lock:
            old = [rid for rid, it in self._items.items() if it["ts"] < cut]
            for rid in old:
                self._items.pop(rid)
        return old


# ----------------------------------------------------------------------------- settings validation
def validate_settings(raw):
    """m.Settings plus the structure the dashboard and the scheduler rely on; returns the cleaned dict."""
    if not isinstance(raw, dict):
        raise Invalid("Settings must be an object")
    try:
        s = m.Settings(raw)
    except m.SettingsError as exc:
        raise Invalid(str(exc))
    errs = []

    def need(cond, what):
        if not cond and what not in errs:
            errs.append(what)
    try:
        need(isinstance(raw["timezone_offset_minutes"], (int, float)) and -720 <= raw["timezone_offset_minutes"] <= 840, "site time zone")
        need(isinstance(raw["due_soon_days"], (int, float)) and raw["due_soon_days"] >= 0, "due soon days")
        mt = raw["meter"]
        need(bool(mt.get("key")) and bool(mt.get("unit")), "meter key and unit")
        need(isinstance(mt.get("valid_min"), (int, float)) and isinstance(mt.get("valid_below"), (int, float))
             and mt["valid_min"] < mt["valid_below"], "meter valid range")
        w = raw["meter_due_window"]
        need(all(isinstance(w.get(k), (int, float)) and w[k] >= 0 for k in ("pct_of_interval", "min_units")), "meter due window")
        need(isinstance(raw["doc_expiry_alert_days"], (int, float)) and raw["doc_expiry_alert_days"] >= 0, "document expiry days")
        need(isinstance(raw["max_upload_mb"], (int, float)) and raw["max_upload_mb"] > 0, "upload size")
        codes = [p.get("code") for p in raw["priorities"]]
        need(all(codes) and len(set(codes)) == len(codes), "priority codes (unique)")
        need(all(p.get("label") and isinstance(p.get("response_days"), (int, float)) and p["response_days"] >= 0
                 for p in raw["priorities"]), "priorities (label and response days)")
        names = [t.get("name") for t in raw["wo_types"]]
        need(all(names) and len(set(names)) == len(names), "work-order type names (unique)")
        fc = raw["failure_codes"]
        need(all(isinstance(fc.get(k), list) and fc[k] for k in ("problem", "cause", "action")), "failure codes")
        ac = raw["attachment_categories"]
        need(isinstance(raw["doc_categories"], list) and bool(ac.get("image")) and bool(ac.get("other")), "document categories")
        cb = raw["condition_based"]
        if cb.get("enabled"):
            need(bool(cb.get("severities")) and bool(cb.get("alarm_types")), "condition-based severities and alarm types")
            need(cb.get("wo_type") in s.types and cb.get("priority") in s.priorities, "condition-based type and priority")
        al = raw["alerts"]
        need(all(c in s.priorities for c in al.get("overdue_priorities", [])), "overdue alert priorities")
        need(isinstance(al.get("digest_hour"), (int, float)) and 0 <= al["digest_hour"] <= 23, "digest hour")
        need(isinstance(al.get("kpi_periods_days"), list) and al["kpi_periods_days"]
             and all(isinstance(x, (int, float)) and x > 0 for x in al["kpi_periods_days"]), "KPI periods")
    except (AttributeError, KeyError, TypeError):
        raise Invalid("Settings are malformed")
    if errs:
        raise Invalid("Please complete: " + ", ".join(errs))
    return raw


# ----------------------------------------------------------------------------- service
class Service:
    """Commands of one verified user. Construct per request."""

    def __init__(self, store, user, config, uploads):
        """config: (settings asset id, attributes of 'Maintenance Settings') as returned by Store.settings_asset()."""
        self.store, self.user, self.uploads = store, user, uploads
        self.sid, attrs = config
        self.raw = attrs.get("cmms_settings") if isinstance(attrs.get("cmms_settings"), dict) else None
        self.rev = attrs.get("cmms_settings_rev")
        self.templates = attrs.get("pm_templates") if isinstance(attrs.get("pm_templates"), dict) else None
        self.roles = attrs.get("cmms_roles") if isinstance(attrs.get("cmms_roles"), dict) else {}
        self.roles_rev = attrs.get("cmms_roles_rev")
        self._settings, self._equipment, self._meta = None, None, {}

    # ------------------------------------------------------------------ context
    @property
    def settings(self):
        if self._settings is None:
            try:
                self._settings = m.Settings(self.raw)
            except m.SettingsError as exc:
                raise Invalid(str(exc))
        return self._settings

    def can(self, action):
        return R.can(self.user.role, action)

    def require(self, action):
        R.require(self.user.role, action)

    def equipment(self):
        """Equipment the user may see: devices of the configured profiles (customer users: assigned to their customer)."""
        if self._equipment is None:
            cid = None if self.user.tenant_admin else self.user.customer_id
            self._equipment = sorted(self.store.equipment(self.settings, cid), key=lambda e: e["name"])
        return self._equipment

    def equip(self, eid):
        for e in self.equipment():
            if e["id"] == eid:
                return e
        raise Invalid("Choose equipment from the list")

    def meta(self, e):
        """Meter, documents and predictive-maintenance configuration of one equipment (loaded once per request)."""
        if e["id"] not in self._meta:
            key = self.settings.meter_key
            has = key in self.store.timeseries_keys(e["id"])
            a = self.store.attrs("DEVICE", e["id"], ["maint_docs", "pm_config"])
            pm = a.get("pm_config") if isinstance(a.get("pm_config"), dict) else None
            self._meta[e["id"]] = {"hasMeter": has, "meter": self.store.meter_reading(e["id"], self.settings) if has else None,
                                   "docs": a.get("maint_docs") or [], "pm": pm}
        return self._meta[e["id"]]

    def library(self):
        lib = self.store.library()
        return lib, ((self.store.attrs("ASSET", lib, ["maint_docs"]).get("maint_docs") or []) if lib else [])

    def hist(self, action, note="", frm=None, to=None):
        return {"ts": now_ms(), "user": self.user.id, "email": self.user.email, "name": self.user.name,
                "action": action, "from": frm, "to": to, "note": note}

    def stamp(self):
        return {"user": self.user.id, "email": self.user.email, "name": self.user.name, "ts": now_ms()}

    def is_me(self, who):
        who = who or {}
        return bool(who) and (who.get("user") in (self.user.id, self.user.email) or
                              (who.get("email") and who.get("email") == self.user.email))

    def local_day(self, ts):
        return datetime.fromtimestamp(ts / 1000, self.settings.tz).date()

    def year(self):
        return datetime.now(self.settings.tz).year

    # ------------------------------------------------------------------ users
    def directory(self):
        """Users of the tenant with their maintenance role (tenant administrators are always admin)."""
        out = []
        for u in self.store.users():
            uid = u["id"]["id"]
            if u.get("authority") == "TENANT_ADMIN":
                role = "admin"
            elif u.get("authority") == "CUSTOMER_USER":
                role = (self.roles.get(uid) or {}).get("role") or ""
                role = role if role in R.CUSTOMER_ROLES else ""
            else:
                continue
            out.append({"id": uid, "name": user_name(u), "email": u.get("email") or "", "authority": u["authority"],
                        "customer_id": (u.get("customerId") or {}).get("id") or "", "role": role})
        return sorted(out, key=lambda x: x["name"].lower())

    def assignees(self):
        """Users who can be assigned work: technician or higher who can see the equipment."""
        out = []
        for u in self.directory():
            if R.rank(u["role"]) < R.rank(R.ASSIGNABLE):
                continue
            # a customer user only sees the equipment of its own customer
            if not self.user.tenant_admin and u["authority"] == "CUSTOMER_USER" and u["customer_id"] != self.user.customer_id:
                continue
            out.append({"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"], "authority": u["authority"],
                        "customer_id": u["customer_id"]})
        # the name is what the form shows and stores: make it unique when two users share a name
        for u in out:
            if sum(1 for x in out if x["name"] == u["name"]) > 1:
                u["label"] = f"{u['name']} ({u['email']})"
        for u in out:
            u["name"] = u.pop("label", u["name"])
        return out

    def assignee(self, p, e_id=None):
        """(name, user id) of the assignee in a form: a user from the list, or free text (vendor / contractor)."""
        aid = text(p, "assignee_id", SHORT * 2)
        if aid:
            for u in self.assignees():
                if u["id"] == aid:
                    return u["name"], aid
            raise Invalid("The selected assignee cannot be assigned work")
        return text(p, "assignee", NAME), ""

    # ------------------------------------------------------------------ state for the dashboard
    def state(self):
        me = {"id": self.user.id, "name": self.user.name, "email": self.user.email, "role": self.user.role,
              "role_label": R.LABELS.get(self.user.role, ""), "can": R.allowed_actions(self.user.role),
              "tenant_admin": self.user.tenant_admin}
        if self.raw is None:
            return {"me": me, "settings": None, "error": "Maintenance settings are not configured (asset 'Maintenance Settings', "
                                                          "attribute cmms_settings). Run period_reports/deploy_dashboard.py once."}
        try:
            self.settings
        except Invalid as exc:
            return {"me": me, "settings": None, "error": str(exc)}
        eq = []
        for e in self.equipment():
            x = dict(e, **self.meta(e))
            if not self.can("pm_save"):
                x["pm"] = {"kind": x["pm"].get("kind")} if x["pm"] and x["pm"].get("kind") else None
            eq.append(x)
        ids = {e["id"] for e in eq}
        lib, docs = self.library()
        out = {"me": me, "settings": self.raw, "settings_rev": self.rev, "equipment": eq, "conditions": m.CONDITIONS,
               "work_orders": [w for w in self.store.work_orders() if w.get("equipment_id") in ids],
               "plans": [p for p in self.store.plans() if p.get("equipment_id") in ids],
               "general": {"id": lib, "docs": docs}, "roles": [{"code": r, "label": R.LABELS[r]} for r in R.ROLES]}
        if self.can("wo_assign_any"):
            out["assignees"] = [{"id": u["id"], "name": u["name"]} for u in self.assignees()]
        if self.can("pm_save"):
            out["templates"] = self.templates
        return out

    # ------------------------------------------------------------------ records
    def wo(self, p, statuses=None):
        w = self.store.work_order(p.get("id"))
        if not w or w.get("equipment_id") not in {e["id"] for e in self.equipment()}:
            raise NotFound("Work order not found")
        if p.get("rev") is not None and w.get("rev") is not None and int(p["rev"]) != int(w["rev"]):
            raise ConflictError(f"{w['number']} was changed by someone else meanwhile. Close this form and open it again.")
        if statuses is not None and w.get("status") not in statuses:
            raise Invalid(f"{w['number']} is {w.get('status')}; this is not possible now")
        w["detail"] = w.get("detail") if isinstance(w.get("detail"), dict) else {}
        return w

    def plan(self, pid, rev=None):
        pl = self.store.plan(pid)
        if not pl or pl.get("equipment_id") not in {e["id"] for e in self.equipment()}:
            raise NotFound("Plan not found")
        if rev is not None and pl.get("rev") is not None and int(rev) != int(pl["rev"]):
            raise ConflictError(f"{pl['number']} was changed by someone else meanwhile. Close this form and open it again.")
        pl["detail"] = pl.get("detail") if isinstance(pl.get("detail"), dict) else {}
        return pl

    def save_wo(self, w, values, detail):
        vals = {"wo_" + k: v for k, v in values.items()}
        vals["wo_detail"] = detail
        self.store.update_work_order(w, vals)

    def may_work(self, w):
        """Technicians work on what is assigned to them or unassigned; supervisors on everything."""
        if self.can("wo_assign_any"):
            return
        aid = w.get("assignee_id") or ""
        if aid and aid != self.user.id:
            raise R.Forbidden(f"{w['number']} is assigned to {w.get('assignee') or 'someone else'}; ask a supervisor to reassign it")

    def doc_ids(self, e):
        _, lib = self.library()
        return {d.get("id") for d in lib} | {d.get("id") for d in self.meta(e)["docs"]}

    def wo_form(self, p, e):
        s = self.settings
        f = {"title": text(p, "title", TITLE, True, "Title"), "type": text(p, "type", SHORT, True, "Type"),
             "priority": text(p, "priority", SHORT, True, "Priority"), "due_date": day(p, "due_date", True, "Due date"),
             "due_rh": number(p, "due_rh", 0, label="due meter reading")}
        if f["type"] not in s.types:
            raise Invalid("Choose a configured work-order type")
        if f["priority"] not in s.priorities:
            raise Invalid("Choose a configured priority")
        if f["due_rh"] is not None and not self.meta(e)["hasMeter"]:
            raise Invalid(f"{e['name']} has no {s.meter_key} meter")
        f["assignee"], f["assignee_id"] = self.assignee(p)
        return f

    def wo_detail(self, p, e, d):
        d = copy.deepcopy(d)
        d["description"] = text(p, "description", TEXT)
        d["checklist"] = lines(p, "checklist")
        docs = _ids(p.get("docs"), "Documents")
        if set(docs) - self.doc_ids(e):
            raise Invalid("A selected document does not exist for this equipment")
        d["docs"] = docs
        d["est_hours"] = number(p, "est_hours", 0, label="estimated hours")
        return d

    def attach(self, e, ids, number_, purpose="attachment"):
        """Link uploaded files to the equipment's documents; returns their metadata."""
        metas = self.uploads.take(_ids(ids, "Attachments"), self.user, purpose)
        if not metas:
            return []
        cats = self.settings.raw["attachment_categories"]
        for x in metas:
            x.update(title=f"{number_} - {x['file']}", wo=number_,
                     category=cats["image"] if re.search(r"\.(jpe?g|png|gif|webp|heic|bmp)$", x["file"], re.I) else cats["other"])
        docs = self.store.attrs("DEVICE", e["id"], ["maint_docs"]).get("maint_docs") or []
        self.store.save_attrs("DEVICE", e["id"], {"maint_docs": docs + metas})
        self._meta.pop(e["id"], None)
        return metas

    # ------------------------------------------------------------------ dispatcher
    def run(self, action, p):
        fn = getattr(self, "do_" + action, None)
        if fn is None:
            raise NotFound(f"Unknown action {action}")
        if not isinstance(p, dict):
            raise Invalid("Request body must be a JSON object")
        with WRITE_LOCK:
            out = fn(p) or {}
        log.info("%s by %s (%s): %s", action, self.user.email, self.user.role, out.get("number") or out.get("id") or "ok")
        return out

    # ------------------------------------------------------------------ work requests
    def do_request_create(self, p):
        self.require("request_create")
        e = self.equip(p.get("equipment_id"))
        title, desc = text(p, "title", TITLE, True, "What is the problem"), text(p, "description", TEXT, True, "Description")
        now = now_ms()
        fields = {"title": title, "type": "", "priority": "", "status": m.REQUESTED, "source": "request", "plan_id": "",
                  "alarm_id": "", "equipment_id": e["id"], "equipment_name": e["name"], "due_date": "", "due_rh": None,
                  "interval_rh": None, "assignee": "", "assignee_id": "", "created_ts": now, "completed_ts": None, "closed_ts": None}
        detail = {"description": desc, "requested_by": self.stamp(), "attachments": [],
                  "history": [self.hist("requested", "Work request raised", None, m.REQUESTED)]}
        files = _ids(p.get("attachments"), "Attachments")
        self.uploads.check(files, self.user, "attachment")
        number_, aid = self.store.create_work_order(fields, detail, self.year())
        if files:
            metas = self.attach(e, files, number_)
            detail["attachments"] = [{"id": a["id"], "title": a["title"], "file": a["file"]} for a in metas]
            self.store.update_work_order({"id": aid, "number": number_, "rev": 1}, {"wo_detail": detail})
        return {"id": aid, "number": number_}

    def do_request_approve(self, p):
        self.require("request_approve")
        w = self.wo(p, [m.REQUESTED])
        e = self.equip(w["equipment_id"])
        f = self.wo_form(dict(p, title=p.get("title") or w["title"]), e)
        d = self.wo_detail(dict(p, description=p.get("description", w["detail"].get("description"))), e, w["detail"])
        d["approved_by"] = self.stamp()
        d["history"] = d.get("history", []) + [self.hist("approved", "Request approved as a work order", m.REQUESTED, m.SCHEDULED)]
        self.save_wo(w, dict(f, status=m.SCHEDULED), d)
        return {"id": w["id"], "number": w["number"]}

    def do_request_reject(self, p):
        self.require("request_approve")
        w = self.wo(p, [m.REQUESTED])
        why = text(p, "reason", NOTE, True, "Reason")
        d = copy.deepcopy(w["detail"])
        d["cancel_reason"] = why
        d["history"] = d.get("history", []) + [self.hist("request rejected", why, m.REQUESTED, m.CANCELLED)]
        self.save_wo(w, {"status": m.CANCELLED, "closed_ts": now_ms()}, d)
        return {"id": w["id"], "number": w["number"]}

    def do_request_withdraw(self, p):
        self.require("request_withdraw")
        w = self.wo(p, [m.REQUESTED])
        if not self.is_me(w["detail"].get("requested_by")) and not self.can("request_approve"):
            raise R.Forbidden("Only the person who raised the request can withdraw it")
        why = text(p, "reason", NOTE, True, "Reason")
        d = copy.deepcopy(w["detail"])
        d["cancel_reason"] = why
        d["history"] = d.get("history", []) + [self.hist("request withdrawn", why, m.REQUESTED, m.CANCELLED)]
        self.save_wo(w, {"status": m.CANCELLED, "closed_ts": now_ms()}, d)
        return {"id": w["id"], "number": w["number"]}

    # ------------------------------------------------------------------ work orders
    def do_wo_create(self, p):
        self.require("wo_create")
        e = self.equip(p.get("equipment_id"))
        f = self.wo_form(p, e)
        d = self.wo_detail(p, e, {})
        d["history"] = [self.hist("created", "Raised manually", None, m.SCHEDULED)]
        fields = dict(f, status=m.SCHEDULED, source="manual", plan_id="", alarm_id="", equipment_id=e["id"],
                      equipment_name=e["name"], interval_rh=None, created_ts=now_ms(), completed_ts=None, closed_ts=None)
        number_, aid = self.store.create_work_order(fields, d, self.year())
        return {"id": aid, "number": number_}

    def do_wo_edit(self, p):
        self.require("wo_edit")
        w = self.wo(p, m.OPEN)
        e = self.equip(w["equipment_id"])
        f = self.wo_form(p, e)
        d = self.wo_detail(p, e, w["detail"])
        changes = [k for k in ("title", "priority", "due_date", "due_rh", "assignee", "type")
                   if str(w.get(k) if w.get(k) is not None else "") != str(f[k] if f[k] is not None else "")]
        d["history"] = d.get("history", []) + [self.hist("edited", "Changed: " + ", ".join(changes) if changes else "Details updated")]
        self.save_wo(w, f, d)
        return {"id": w["id"], "number": w["number"]}

    def do_wo_start(self, p):
        self.require("wo_start")
        w = self.wo(p, [m.SCHEDULED, m.ON_HOLD])
        self.may_work(w)
        m.check_transition(w["status"], m.IN_PROGRESS)
        d = copy.deepcopy(w["detail"])
        d["hold_reason"] = None
        d["started_ts"] = d.get("started_ts") or now_ms()
        vals = {"status": m.IN_PROGRESS}
        if not w.get("assignee_id") and not w.get("assignee") and not self.can("wo_assign_any"):
            vals.update(assignee=self.user.name, assignee_id=self.user.id)          # a technician takes unassigned work
        d["history"] = d.get("history", []) + [self.hist("resumed" if w["status"] == m.ON_HOLD else "started", "", w["status"], m.IN_PROGRESS)]
        self.save_wo(w, vals, d)
        return {"id": w["id"], "number": w["number"]}

    def do_wo_hold(self, p):
        self.require("wo_hold")
        w = self.wo(p, [m.SCHEDULED, m.IN_PROGRESS])
        self.may_work(w)
        why = text(p, "reason", NOTE, True, "Reason")
        d = copy.deepcopy(w["detail"])
        d["hold_reason"] = why
        d["history"] = d.get("history", []) + [self.hist("put on hold", why, w["status"], m.ON_HOLD)]
        self.save_wo(w, {"status": m.ON_HOLD}, d)
        return {"id": w["id"], "number": w["number"]}

    def do_wo_reject(self, p):
        self.require("wo_reject")
        w = self.wo(p, [m.COMPLETED])
        why = text(p, "reason", NOTE, True, "What must be reworked")
        d = copy.deepcopy(w["detail"])
        d["rework"] = int(d.get("rework") or 0) + 1
        d["history"] = d.get("history", []) + [self.hist("rejected by verifier", why, m.COMPLETED, m.IN_PROGRESS)]
        self.save_wo(w, {"status": m.IN_PROGRESS, "completed_ts": None}, d)
        return {"id": w["id"], "number": w["number"]}

    def do_wo_verify(self, p):
        self.require("wo_verify")
        w = self.wo(p, [m.COMPLETED])
        if self.settings.raw["verification"].get("different_user") and self.is_me(w["detail"].get("completed_by")):
            raise R.Forbidden("You recorded this work, so another user must verify it")
        d = copy.deepcopy(w["detail"])
        d["verified_by"] = self.stamp()
        d["history"] = d.get("history", []) + [self.hist("verified and closed", "", m.COMPLETED, m.CLOSED)]
        self.save_wo(w, {"status": m.CLOSED, "closed_ts": now_ms()}, d)
        return {"id": w["id"], "number": w["number"]}

    def do_wo_cancel(self, p):
        self.require("wo_cancel")
        w = self.wo(p, m.OPEN)
        why = text(p, "reason", NOTE, True, "Reason")
        d = copy.deepcopy(w["detail"])
        d["cancel_reason"] = why
        d["history"] = d.get("history", []) + [self.hist("cancelled", why, w["status"], m.CANCELLED)]
        self.save_wo(w, {"status": m.CANCELLED, "closed_ts": now_ms()}, d)
        if w.get("plan_id"):
            try:
                pl = self.plan(w["plan_id"])
            except NotFound:
                pl = None
            if pl:
                upd = {"plan_" + k: v for k, v in m.next_due_after_skip(pl, w).items()}
                pd = copy.deepcopy(pl["detail"])
                pd["history"] = pd.get("history", []) + [self.hist("occurrence skipped", f"{w['number']} cancelled: {why}")]
                upd["plan_detail"] = pd
                self.store.update_plan(pl, upd)
        return {"id": w["id"], "number": w["number"]}

    def do_wo_delete(self, p):
        """Permanently remove a work order (maintenance administrator). An open work order raised by a plan must be
        cancelled first so that the plan skips that occurrence instead of raising it again."""
        self.require("wo_delete")
        w = self.wo(p)
        if w.get("plan_id") and w.get("status") in m.OPEN:
            raise Invalid(f"{w['number']} belongs to a maintenance plan; cancel it first, then delete it")
        self.store.delete_work_order(w["id"])
        return {"id": w["id"], "number": w["number"]}

    def do_wo_complete(self, p):
        """Record the work done on a work order, or (draft) work carried out without one."""
        s, now = self.settings, now_ms()
        draft = p.get("draft")
        if draft is not None:
            self.require("done_record")
            if not isinstance(draft, dict):
                raise Invalid("Invalid work record")
            e = self.equip(draft.get("equipment_id"))
            wtype = text(draft, "type", SHORT, True, "Type")
            if wtype not in s.types:
                raise Invalid("Choose a configured work-order type")
            dtitle = text(draft, "title", TITLE, True, "Work title")
            dpri = text(draft, "priority", SHORT)
            if dpri and dpri not in s.priorities:
                raise Invalid("Choose a configured priority")
            rep = number(draft, "reported_ts", 0, label="reported time", integer=True) if s.types[wtype].get("failure_codes") else None
            if rep is not None and rep > now + 60000:
                raise Invalid("The reported time cannot be in the future")
            ddesc = text(draft, "description", TEXT)
            w, pl, checklist = None, None, []
        else:
            self.require("wo_complete")
            w = self.wo(p, [m.SCHEDULED, m.IN_PROGRESS])
            self.may_work(w)
            m.check_transition(w["status"], m.COMPLETED)
            e = self.equip(w["equipment_id"])
            wtype = w.get("type")
            pl = None
            if w.get("plan_id"):
                try:
                    pl = self.plan(w["plan_id"])
                except NotFound:
                    pl = None
            checklist = w["detail"].get("checklist") or []

        ty, meta = s.types.get(wtype) or {}, self.meta(e)
        finished = number(p, "finished_ts", 1, True, "finish time", integer=True)
        if finished > now + 60000:
            raise Invalid("The finish time cannot be in the future")
        started = number(p, "started_ts", 1, True, "start time", integer=True)
        if started > finished:
            raise Invalid("The work cannot start after it finished")
        condition = text(p, "condition", SHORT, True, "Equipment condition after the work")
        if condition not in m.CONDITIONS:
            raise Invalid("Choose the equipment condition after the work")
        cond_note = text(p, "condition_note", NOTE)
        if condition != m.CONDITIONS[0] and not cond_note:
            raise Invalid("Describe the limitation / why the equipment is out of service")
        fu = p.get("follow_up") if isinstance(p.get("follow_up"), dict) else None
        if fu is not None:
            fu = {"title": text(fu, "title", TITLE, True, "Follow-up work"), "description": text(fu, "description", TEXT)}
        tech, work = text(p, "technician", NAME, True, "Technician / vendor"), text(p, "work_done", LONG_TEXT, True, "Work done")
        lab = number(p, "labour_hours", 0, True, "labour hours")
        down = number(p, "downtime_hours", 0, True, "downtime hours (0 if none)")
        rh = number(p, "done_rh", 0, label="meter reading")
        if rh is not None and not meta["hasMeter"]:
            raise Invalid(f"{e['name']} has no {s.meter_key} meter")
        if rh is not None and not s.valid_meter(rh):
            raise Invalid("The meter reading is outside the configured valid range")
        pm = meta["pm"]
        svc = bool(ty.get("pm_service_reset")) and bool(pm and pm.get("kind")) and meta["hasMeter"]
        reset = bool(p.get("service_reset"))
        if reset and not svc:
            raise Invalid("The service countdown cannot be restarted for this work")
        if reset and not isinstance((pm or {}).get("limits"), dict):
            raise Invalid("This equipment has no predictive-maintenance limits to restart")
        if (svc or (pl and pl.get("strategy") == "meter")) and rh is None:
            raise Invalid("Enter the meter reading at the time of work")
        res = p.get("results") or []
        if not isinstance(res, list) or len(res) != len(checklist):
            raise Invalid("Tick or remark every checklist step")
        results = []
        for item, r in zip(checklist, res):
            r = r if isinstance(r, dict) else {}
            note = text(r, "note", 300)
            if not r.get("done") and not note:
                raise Invalid("Enter a remark for each checklist step not done")
            results.append({"item": item, "done": bool(r.get("done")), "note": note})
        failure = None
        if ty.get("failure_codes"):
            fp = p.get("failure") if isinstance(p.get("failure"), dict) else {}
            failure = {k: text(fp, k, NAME) for k in ("problem", "cause", "action")}
            if any(failure[k] not in s.raw["failure_codes"][k] for k in failure):
                raise Invalid("Choose the failure problem, cause and action")
        parts = []
        raw_parts = p.get("parts") or []
        if not isinstance(raw_parts, list) or len(raw_parts) > MAX_LIST:
            raise Invalid("Invalid parts list")
        for x in raw_parts:
            x = x if isinstance(x, dict) else {}
            name = text(x, "name", 100)
            if name:
                parts.append({"name": name, "qty": number(x, "qty", 0, True, "part quantity"),
                              "rate": number(x, "rate", 0, True, "part rate")})
        cost = round(sum(x["qty"] * x["rate"] for x in parts), 2)
        files = _ids(p.get("attachments"), "Attachments")
        self.uploads.check(files, self.user, "attachment")

        if w is None:                    # work recorded without a work order: created only now, with the work
            det0 = {"description": ddesc, "direct": True, "reported_ts": rep,
                    "history": [self.hist("created", "Recorded as work done", None, m.SCHEDULED)]}
            fields = {"title": dtitle, "type": wtype, "priority": dpri, "status": m.SCHEDULED, "source": "direct", "plan_id": "",
                      "alarm_id": "", "equipment_id": e["id"], "equipment_name": e["name"], "due_date": "", "due_rh": None,
                      "interval_rh": None, "assignee": tech, "assignee_id": "", "created_ts": now, "completed_ts": None, "closed_ts": None}
            number_, aid = self.store.create_work_order(fields, det0, self.year())
            w = dict(fields, id=aid, number=number_, rev=1, detail=det0)
        att = self.attach(e, files, w["number"])
        att_ref = [{"id": a["id"], "title": a["title"], "file": a["file"]} for a in att]
        d = copy.deepcopy(w["detail"])
        d.update(results=results, work_done=work, technician=tech, done_rh=rh, labour_hours=lab, downtime_hours=down,
                 parts=parts, cost_total=cost, failure=failure, attachments=(d.get("attachments") or []) + att_ref,
                 service_reset=reset, completed_by=self.stamp(), work_started_ts=started, condition_after=condition,
                 condition_note=cond_note)
        if fu:
            # further work found during this job: a work request for the supervisor, linked both ways
            ffields = {"title": fu["title"], "type": "", "priority": "", "status": m.REQUESTED, "source": "request", "plan_id": "",
                       "alarm_id": "", "equipment_id": e["id"], "equipment_name": e["name"], "due_date": "", "due_rh": None,
                       "interval_rh": None, "assignee": "", "assignee_id": "", "created_ts": now, "completed_ts": None, "closed_ts": None}
            fdet = {"description": fu["description"] or f"Found during {w['number']}: {work[:300]}", "requested_by": self.stamp(),
                    "attachments": [], "follow_up_of": {"id": w["id"], "number": w["number"]},
                    "history": [self.hist("requested", f"Follow-up of {w['number']}", None, m.REQUESTED)]}
            fnum, fid = self.store.create_work_order(ffields, fdet, self.year())
            d["follow_up"] = {"id": fid, "number": fnum, "title": fu["title"]}
        d["history"] = d.get("history", []) + [self.hist("completed", work[:200], w["status"], m.COMPLETED)]
        self.save_wo(w, {"status": m.COMPLETED, "completed_ts": finished}, d)

        plan_upd = {"plan_" + k: v for k, v in m.next_due_after_completion(pl, self.local_day(finished), rh).items()} if pl else None
        nxt = None
        if plan_upd:
            nxt = plan_upd.get("plan_next_due_date") or (f"{plan_upd['plan_next_due_rh']} {s.raw['meter']['unit']}"
                                                         if plan_upd.get("plan_next_due_rh") is not None else None)
        rec = {"type": wtype, "description": work, "technician": tech, "run_hours": rh,
               "parts": ", ".join(f"{x['name']} x{x['qty']:g}" for x in parts) or None, "cost": cost or None, "next_due": nxt,
               "service_reset": reset, "logged_by": self.user.name, "logged_at": now, "wo_number": w["number"],
               "job_title": w["title"], "checklist": results, "labour_hours": lab, "downtime_hours": down, "failure": failure,
               "attachments": att_ref, "started_at": started, "condition_after": condition, "condition_note": cond_note or None,
               "follow_up": d.get("follow_up", {}).get("number")}
        self.store.save_record(e["id"], finished, {"maintenance_record": json.dumps(rec)})
        if pl:
            pd = copy.deepcopy(pl["detail"])
            pd.update(last_done_ts=finished, last_wo=w["number"])
            pd["history"] = pd.get("history", []) + [self.hist("occurrence completed", w["number"])]
            plan_upd["plan_detail"] = pd
            self.store.update_plan(pl, plan_upd)
        if reset:
            pc = self.store.attrs("DEVICE", e["id"], ["pm_config"]).get("pm_config")
            pc["limits"].setdefault("service", {})
            pc["limits"]["service"]["last_service_run_hours"] = rh
            if pl and pl.get("strategy") == "meter" and float(pl.get("interval_rh") or 0) > 0:
                pc["limits"]["service"]["interval_h"] = float(pl["interval_rh"])
            self.store.save_attrs("DEVICE", e["id"], {"pm_config": pc})
        return {"id": w["id"], "number": w["number"], "follow_up": d.get("follow_up")}

    # ------------------------------------------------------------------ plans
    def do_plan_save(self, p):
        self.require("plan_save")
        s = self.settings
        pl = self.plan(p.get("id"), p.get("rev")) if p.get("id") else None
        e = self.equip(pl["equipment_id"] if pl else p.get("equipment_id"))
        title, ptype, pri = text(p, "title", TITLE, True, "Title"), text(p, "type", SHORT, True, "Type"), text(p, "priority", SHORT, True, "Priority")
        if ptype not in s.types or not s.types[ptype].get("plan_allowed"):
            raise Invalid("Choose a work-order type that is allowed in plans")
        if pri not in s.priorities:
            raise Invalid("Choose a configured priority")
        strategy = text(p, "strategy", 10, True, "Strategy")
        if strategy not in ("time", "meter"):
            raise Invalid("Strategy must be time or meter")
        meter = strategy == "meter"
        if meter and not self.meta(e)["hasMeter"]:
            raise Invalid(f"{e['name']} has no {s.meter_key} meter")
        if meter:
            irh, nrh = number(p, "interval_rh", 1, True, "interval"), number(p, "next_due_rh", 0, True, "next due reading")
            days_, date_, lead = None, None, None
        else:
            days_ = number(p, "interval_days", 1, True, "interval (days)", integer=True)
            date_ = day(p, "next_due_date", True, "Next due date")
            lead = number(p, "lead_days", 0, True, "lead days", integer=True)
            irh, nrh = None, None
        d = self.wo_detail(dict(p, description=""), e, pl["detail"] if pl else {})
        d.pop("description", None)
        d["assignee"], d["assignee_id"] = self.assignee(p)
        d["notes"] = text(p, "notes", 300)
        d["history"] = d.get("history", []) + [self.hist("edited" if pl else "created", "")]
        vals = {"plan_title": title, "plan_type": ptype, "plan_priority": pri, "plan_strategy": strategy,
                "plan_interval_days": days_, "plan_interval_rh": irh, "plan_lead_days": lead, "plan_next_due_date": date_,
                "plan_next_due_rh": nrh, "plan_equipment_id": e["id"], "plan_equipment_name": e["name"], "plan_detail": d}
        if pl:
            self.store.update_plan(pl, vals)
            return {"id": pl["id"], "number": pl["number"]}
        vals["plan_active"] = True
        number_, aid = self.store.create_plan(vals, title)
        return {"id": aid, "number": number_}

    def do_plan_toggle(self, p):
        self.require("plan_toggle")
        pl = self.plan(p.get("id"), p.get("rev"))
        active = pl.get("active") is False
        pd = copy.deepcopy(pl["detail"])
        pd["history"] = pd.get("history", []) + [self.hist("resumed" if active else "paused", "")]
        self.store.update_plan(pl, {"plan_active": active, "plan_detail": pd})
        return {"id": pl["id"], "number": pl["number"]}

    def do_plan_raise(self, p):
        self.require("plan_raise")
        pl = self.plan(p.get("id"))
        if pl.get("active") is False:
            raise Invalid(f"{pl['number']} is paused")
        if any(w.get("plan_id") == pl["id"] and w.get("status") in m.ACTIVE for w in self.store.work_orders()):
            raise Invalid("This plan already has an active work order")
        fields, detail = wo_from_plan(pl, now_ms())
        detail["history"] = [self.hist("created", f"Raised from plan {pl['number']} ahead of schedule", None, m.SCHEDULED)]
        number_, aid = self.store.create_work_order(fields, detail, self.year())
        return {"id": aid, "number": number_}

    # ------------------------------------------------------------------ documents
    def owner(self, owner):
        if owner == "general":
            # the general library is shared by all customers of the tenant
            if not self.user.tenant_admin:
                raise R.Forbidden("Documents for all equipment are managed by the tenant administrator")
            lib, docs = self.library()
            if not lib:
                raise Invalid("The general document library does not exist")
            return "ASSET", lib, docs
        e = self.equip(owner)
        return "DEVICE", e["id"], self.meta(e)["docs"]

    def do_doc_add(self, p):
        self.require("doc_add")
        s = self.settings
        etype, oid, docs = self.owner(p.get("owner"))
        cat = text(p, "category", SHORT * 2, True, "Category")
        if cat not in s.raw["doc_categories"]:
            raise Invalid("Choose a configured document category")
        title = text(p, "title", TITLE, True, "Title")
        meta = self.uploads.take(_ids([p.get("file_id")] if p.get("file_id") else [], "File"), self.user, "document")
        if not meta:
            raise Invalid("Choose a file")
        meta = dict(meta[0], title=title, category=cat, doc_no=text(p, "doc_no", SHORT) or None,
                    revision=text(p, "revision", 20) or None, expiry=day(p, "expiry", False, "Valid until") or None)
        self.store.save_attrs(etype, oid, {"maint_docs": docs + [meta]})
        return {"id": meta["id"]}

    def do_doc_delete(self, p):
        self.require("doc_delete")
        etype, oid, docs = self.owner(p.get("owner"))
        did = str(p.get("id") or "")
        if did not in {d.get("id") for d in docs}:
            raise NotFound("Document not found")
        self.store.delete_resource(did)
        self.store.save_attrs(etype, oid, {"maint_docs": [d for d in docs if d.get("id") != did]})
        for pl in self.store.plans():
            pd = pl.get("detail") if isinstance(pl.get("detail"), dict) else {}
            if did in (pd.get("docs") or []):
                pd["docs"] = [x for x in pd["docs"] if x != did]
                self.store.update_plan(pl, {"plan_detail": pd})
        return {"id": did}

    def visible_file(self, rid):
        """True when the file is a document / attachment of equipment the user may see, or of the general library."""
        _, lib = self.library()
        if rid in {d.get("id") for d in lib}:
            return True
        return any(rid in {d.get("id") for d in self.meta(e)["docs"]} for e in self.equipment())

    # ------------------------------------------------------------------ configuration
    def do_settings_save(self, p):
        self.require("settings_save")
        if not self.sid:
            raise Invalid("The asset 'Maintenance Settings' does not exist")
        if p.get("rev") is not None and self.rev is not None and int(p["rev"]) != int(self.rev):
            raise ConflictError("The settings were changed by someone else meanwhile; reload the page")
        raw = validate_settings(p.get("settings"))
        self.store.save_attrs("ASSET", self.sid, {"cmms_settings": raw, "cmms_settings_rev": int(self.rev or 0) + 1})
        return {"rev": int(self.rev or 0) + 1}

    def pm_equipment(self, eid):
        e = self.equip(eid)
        pc = self.store.attrs("DEVICE", e["id"], ["pm_config"]).get("pm_config")
        return e, (pc if isinstance(pc, dict) else {})

    def do_pm_save(self, p):
        self.require("pm_save")
        e, pc = self.pm_equipment(p.get("equipment_id"))
        if not pc.get("kind"):
            raise Invalid(f"{e['name']} has no predictive-maintenance configuration")
        engine, limits = p.get("engine"), p.get("limits")
        if not isinstance(engine, dict) or not isinstance(limits, dict):
            raise Invalid("Engine and limits must be objects")
        pc.update(engine=engine, limits=limits)
        self.store.save_attrs("DEVICE", e["id"], {"pm_config": pc})
        done = [e["name"]]
        if p.get("apply_engine_all"):
            for o in self.equipment():
                if o["id"] == e["id"]:
                    continue
                oc = self.store.attrs("DEVICE", o["id"], ["pm_config"]).get("pm_config")
                if isinstance(oc, dict) and oc.get("kind"):
                    oc["engine"] = copy.deepcopy(engine)
                    self.store.save_attrs("DEVICE", o["id"], {"pm_config": oc})
                    done.append(o["name"])
        return {"saved": done}

    def do_pm_enable(self, p):
        self.require("pm_enable")
        e, pc = self.pm_equipment(p.get("equipment_id"))
        if pc.get("kind"):
            raise Invalid(f"{e['name']} already has predictive maintenance")
        kind = ((self.templates or {}).get("profiles") or {}).get(e["type"])
        if not kind or kind not in (self.templates.get("kinds") or {}):
            raise Invalid(f"No predictive-maintenance template for profile {e['type']}")
        pc.update(kind=kind, engine=copy.deepcopy(self.templates["engine"]), limits=copy.deepcopy(self.templates["kinds"][kind]))
        self.store.save_attrs("DEVICE", e["id"], {"pm_config": pc})
        return {"kind": kind}

    def do_role_save(self, p):
        self.require("role_save")
        if not self.sid:
            raise Invalid("The asset 'Maintenance Settings' does not exist")
        if p.get("rev") is not None and self.roles_rev is not None and int(p["rev"]) != int(self.roles_rev):
            raise ConflictError("Roles were changed by someone else meanwhile; reload the page")
        uid, role = str(p.get("user_id") or ""), str(p.get("role") or "")
        if role and role not in R.CUSTOMER_ROLES:
            raise Invalid("Choose one of the customer roles (the administrator role belongs to tenant administrators)")
        target = next((u for u in self.directory() if u["id"] == uid), None)
        if not target:
            raise NotFound("User not found")
        if target["authority"] != "CUSTOMER_USER":
            raise Invalid("Tenant administrators are always maintenance administrators")
        roles = copy.deepcopy(self.roles)
        if role:
            roles[uid] = {"role": role, "name": target["name"], "email": target["email"], "customer_id": target["customer_id"],
                          "set_by": self.user.name, "set_ts": now_ms()}
        else:
            roles.pop(uid, None)
        rev = int(self.roles_rev or 0) + 1
        self.store.save_attrs("ASSET", self.sid, {"cmms_roles": roles, "cmms_roles_rev": rev})
        log.info("role of %s set to %s by %s", target["email"], role or "none", self.user.email)
        return {"rev": rev}

    def users_view(self):
        self.require("role_save")
        names = self.store.customers()
        return {"users": [dict(u, customer=names.get(u["customer_id"], "")) for u in self.directory()],
                "roles": [{"code": r, "label": R.LABELS[r]} for r in R.CUSTOMER_ROLES], "rev": self.roles_rev}

    def profiles_view(self):
        self.require("settings_save")
        return {"profiles": self.store.device_profiles()}


__all__ = ["Service", "User", "Uploads", "Invalid", "NotFound", "ConflictError", "StoreError", "validate_settings"]
