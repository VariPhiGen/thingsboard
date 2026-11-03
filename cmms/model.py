"""CMMS domain rules: work-order lifecycle, PM due logic, KPIs (EN 13306 / ISO 14224 terminology).

No business values live here: priorities, SLA days, due windows, work-order types, failure codes, time zone, etc. come
from the ThingsBoard configuration (asset "Maintenance Settings", attribute cmms_settings), wrapped by Settings below.
Only the work-order lifecycle (states and allowed transitions) is defined in code, because it is the workflow itself.
The dashboard widget (period_reports/widgets/maintenance_planner.js) implements the same rules in JavaScript.
"""
import fnmatch
from datetime import date, datetime, timedelta, timezone

# ----------------------------------------------------------------------------- lifecycle (workflow definition)
SCHEDULED, IN_PROGRESS, ON_HOLD, COMPLETED, CLOSED, CANCELLED = (
    "Scheduled", "In Progress", "On Hold", "Completed", "Closed", "Cancelled")
OPEN = {SCHEDULED, IN_PROGRESS, ON_HOLD}          # work still to be done
ACTIVE = OPEN | {COMPLETED}                       # not yet closed
TRANSITIONS = {
    SCHEDULED: {IN_PROGRESS, ON_HOLD, CANCELLED, COMPLETED},
    IN_PROGRESS: {ON_HOLD, COMPLETED, CANCELLED},
    ON_HOLD: {IN_PROGRESS, CANCELLED},
    COMPLETED: {CLOSED, IN_PROGRESS},             # verify & close, or reject back to work
    CLOSED: set(),
    CANCELLED: set(),
}

REQUIRED = ["timezone_offset_minutes", "equipment_profiles", "meter", "priorities", "wo_types", "due_soon_days",
            "meter_due_window", "failure_codes", "doc_categories", "attachment_categories", "doc_expiry_alert_days",
            "max_upload_mb", "verification", "condition_based", "alerts"]


class SettingsError(ValueError):
    pass


class TransitionError(ValueError):
    pass


class Settings:
    """Validated view of cmms_settings. Missing values raise SettingsError (nothing is assumed)."""

    def __init__(self, raw):
        if not isinstance(raw, dict):
            raise SettingsError("Maintenance settings are not configured (asset 'Maintenance Settings', attribute cmms_settings)")
        missing = [k for k in REQUIRED if raw.get(k) in (None, "", [], {})]
        if missing:
            raise SettingsError("Maintenance settings incomplete: " + ", ".join(missing))
        self.raw = raw
        self.tz = timezone(timedelta(minutes=int(raw["timezone_offset_minutes"])))
        self.priorities = {p["code"]: p for p in raw["priorities"]}
        self.types = {t["name"]: t for t in raw["wo_types"]}
        self.planned_types = {n for n, t in self.types.items() if t.get("planned")}
        self.corrective_types = {n for n, t in self.types.items() if t.get("failure_codes")}
        self.meter_key = raw["meter"]["key"]
        self.cbm = raw["condition_based"]
        self.alerts = raw["alerts"]

    def response_days(self, priority):
        if priority not in self.priorities:
            raise SettingsError(f"Priority {priority!r} is not configured")
        return int(self.priorities[priority]["response_days"])

    def meter_window(self, interval):
        w = self.raw["meter_due_window"]
        return max(float(w["min_units"]), float(interval or 0) * float(w["pct_of_interval"]) / 100.0)

    def valid_meter(self, v):
        m = self.raw["meter"]
        return float(m["valid_min"]) <= v < float(m["valid_below"])

    def cbm_alarm(self, alarm):
        c = self.cbm
        return bool(c.get("enabled")) and alarm.get("severity") in c.get("severities", []) and \
            any(fnmatch.fnmatchcase(alarm.get("type") or "", pat) for pat in c.get("alarm_types", []))


def check_transition(current, target, wo=None, user=None, settings=None):
    """Raise TransitionError when the lifecycle does not allow current -> target (or segregation is violated)."""
    if target not in TRANSITIONS.get(current, set()):
        raise TransitionError(f"A work order in status '{current}' cannot be moved to '{target}'")
    if target == CLOSED and wo is not None and settings is not None and settings.raw["verification"].get("different_user"):
        done_by = ((wo.get("detail") or {}).get("completed_by") or {}).get("user")
        if done_by and user and done_by == user:
            raise TransitionError("The person who recorded the work cannot verify it; another user must verify and close")


# ----------------------------------------------------------------------------- dates
def today_local(settings, now=None):
    return (now or datetime.now(settings.tz)).astimezone(settings.tz).date()


def parse_date(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


# ----------------------------------------------------------------------------- work-order due state
def due_state(wo, run_hours, today, settings):
    """'overdue' | 'due' | 'upcoming' | 'done' | 'closed' | 'unknown' for a work order."""
    status = wo.get("status")
    if status in (CLOSED, CANCELLED):
        return "closed"
    if status == COMPLETED:
        return "done"
    due_rh = wo.get("due_rh")
    if due_rh not in (None, ""):
        if run_hours is None:
            return "unknown"
        left = float(due_rh) - float(run_hours)
        if left < 0:
            return "overdue"
        return "due" if left <= settings.meter_window(wo.get("interval_rh")) else "upcoming"
    due = parse_date(wo.get("due_date"))
    if not due:
        return "unknown"
    if due < today:
        return "overdue"
    return "due" if (due - today).days <= int(settings.raw["due_soon_days"]) else "upcoming"


# ----------------------------------------------------------------------------- plans
def plan_generation_due(plan, run_hours, today, settings):
    """True when the plan's next occurrence is inside its lead time (a work order should exist for it)."""
    if plan.get("active") is False:
        return False
    if plan.get("strategy") == "meter":
        nxt = plan.get("next_due_rh")
        if nxt in (None, "") or run_hours is None:
            return False
        return float(run_hours) >= float(nxt) - settings.meter_window(plan.get("interval_rh"))
    nxt = parse_date(plan.get("next_due_date"))
    if not nxt or plan.get("lead_days") in (None, ""):
        return False
    return (nxt - today).days <= int(plan["lead_days"])


def next_due_after_completion(plan, done_date, done_rh=None):
    """Plan fields to update after a work order of the plan is completed (time: from work date; meter: from reading)."""
    if plan.get("strategy") == "meter":
        if done_rh is None:
            raise ValueError("The meter reading at completion is required for a meter-based plan")
        return {"next_due_rh": round(float(done_rh) + float(plan["interval_rh"]), 1)}
    days = int(plan.get("interval_days") or 0)
    if days <= 0:
        return {"active": False}
    return {"next_due_date": (parse_date(done_date) + timedelta(days=days)).isoformat()}


def next_due_after_skip(plan, wo):
    """Plan fields when a plan's work order is cancelled: that occurrence is skipped, the next one is one interval
    after the cancelled due point (otherwise the scheduler would immediately raise the same work order again)."""
    if plan.get("strategy") == "meter":
        base = wo.get("due_rh") if wo.get("due_rh") not in (None, "") else plan.get("next_due_rh")
        return {"next_due_rh": round(float(base) + float(plan["interval_rh"]), 1)}
    days = int(plan.get("interval_days") or 0)
    if days <= 0:
        return {"active": False}
    base = parse_date(wo.get("due_date")) or parse_date(plan.get("next_due_date"))
    return {"next_due_date": (base + timedelta(days=days)).isoformat()}


def due_date_for_priority(priority, created, settings):
    return (created + timedelta(days=settings.response_days(priority))).isoformat()


# ----------------------------------------------------------------------------- KPIs
def kpis(work_orders, start, end, today, settings, run_hours=None):
    """SMRP-style KPIs over [start, end] (dates, inclusive); None where there is no data.

    pm_compliance_pct  planned WOs due in the period that were completed on or before their due date
    backlog / overdue  open WOs now
    mttr_h             mean time to complete corrective WOs (raised -> completed) completed in the period
    planned_pct        share of planned work among WOs completed in the period
    """
    run_hours = run_hours or {}

    def day(ts):
        return datetime.fromtimestamp(ts / 1000, settings.tz).date() if ts else None
    due_in, on_time, done = 0, 0, []
    for w in work_orders:
        if w.get("status") == CANCELLED:
            continue
        due, completed = parse_date(w.get("due_date")), day(w.get("completed_ts"))
        if w.get("type") in settings.planned_types and due and start <= due <= end:
            due_in += 1
            if completed and completed <= due:
                on_time += 1
        if completed and start <= completed <= end:
            done.append(w)
    corrective = [w for w in done if w.get("type") in settings.corrective_types]
    # repair time runs from when the problem was raised; work recorded afterwards counts only with its reported time
    def raised(w):
        return (w.get("detail") or {}).get("reported_ts") if w.get("source") == "direct" else w.get("created_ts")
    mttr = [(w["completed_ts"] - raised(w)) / 3600000 for w in corrective if raised(w) and w.get("completed_ts")]
    open_wos = [w for w in work_orders if w.get("status") in OPEN]
    overdue = [w for w in open_wos if due_state(w, run_hours.get(w.get("equipment_id")), today, settings) == "overdue"]
    labour = sum(float((w.get("detail") or {}).get("labour_hours") or 0) for w in done)
    cost = sum(float((w.get("detail") or {}).get("cost_total") or 0) for w in done)
    return {
        "pm_due": due_in, "pm_on_time": on_time,
        "pm_compliance_pct": round(on_time * 100.0 / due_in, 1) if due_in else None,
        "backlog": len(open_wos), "overdue": len(overdue),
        "completed": len(done), "corrective_completed": len(corrective),
        "mttr_h": round(sum(mttr) / len(mttr), 1) if mttr else None,
        "planned_pct": round((len(done) - len(corrective)) * 100.0 / len(done), 1) if done else None,
        "labour_hours": round(labour, 1), "cost_total": round(cost, 2),
    }
