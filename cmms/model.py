"""CMMS domain rules: work-order lifecycle, PM due logic, KPIs (EN 13306 / ISO 14224 terminology).

Kept free of I/O so the scheduler and the tests share one definition. The dashboard widget
(period_reports/widgets/maintenance_planner.js) implements the same rules in JavaScript.
"""
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# ----------------------------------------------------------------------------- vocabulary
WO_TYPES = ["Preventive", "Inspection", "Corrective", "Statutory", "Calibration", "Condition-based"]
PLANNED_TYPES = {"Preventive", "Inspection", "Statutory", "Calibration"}
PRIORITIES = {"P1": "P1 - Emergency (24 h)", "P2": "P2 - Urgent (3 days)", "P3": "P3 - Normal (7 days)", "P4": "P4 - Low (30 days)"}
PRIORITY_DAYS = {"P1": 1, "P2": 3, "P3": 7, "P4": 30}

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

# Simplified ISO 14224 failure coding (failure mode / cause / maintenance action)
FAILURE_PROBLEM = ["Fails to start", "Fails while running", "Overheating", "Abnormal noise / vibration", "Leakage",
                   "Low output / performance", "Electrical fault", "Instrument / sensor fault", "Low pressure",
                   "Structural damage", "Other"]
FAILURE_CAUSE = ["Wear / ageing", "Lack of maintenance", "Contamination", "Operating error", "Design / installation",
                 "Power supply", "Material defect", "External / environment", "Unknown"]
FAILURE_ACTION = ["Replace", "Repair", "Adjust / calibrate", "Clean", "Refill / recharge", "Tighten / secure",
                  "Settings / software change", "Temporary fix", "No fault found"]


class TransitionError(ValueError):
    pass


def check_transition(current, target, wo=None, user=None):
    """Raise TransitionError when the lifecycle does not allow current -> target (or segregation is violated)."""
    if target not in TRANSITIONS.get(current, set()):
        raise TransitionError(f"A work order in status '{current}' cannot be moved to '{target}'")
    if target == CLOSED and wo is not None:
        done_by = ((wo.get("detail") or {}).get("completed_by") or {}).get("user")
        if done_by and user and done_by == user:
            raise TransitionError("The person who recorded the work cannot verify it; another user must verify and close")


# ----------------------------------------------------------------------------- dates
def today_ist(now=None):
    return (now or datetime.now(IST)).astimezone(IST).date()


def parse_date(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def meter_window(interval_rh):
    """Run-hours before the due point at which a meter-based job counts as due (10 % of the interval, min 10 h)."""
    return max(10.0, float(interval_rh or 0) * 0.1)


# ----------------------------------------------------------------------------- work-order due state
def due_state(wo, run_hours=None, today=None):
    """'overdue' | 'due' | 'upcoming' | 'done' | 'closed' | 'unknown' for a work order."""
    today = today or today_ist()
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
        return "due" if left <= meter_window(wo.get("interval_rh") or 0) else "upcoming"
    due = parse_date(wo.get("due_date"))
    if not due:
        return "unknown"
    if due < today:
        return "overdue"
    return "due" if (due - today).days <= 7 else "upcoming"


# ----------------------------------------------------------------------------- plans
def plan_generation_due(plan, run_hours=None, today=None):
    """True when the plan's next occurrence is inside its lead time (a work order should exist for it)."""
    if not plan.get("active", True):
        return False
    today = today or today_ist()
    if plan.get("strategy") == "meter":
        nxt = plan.get("next_due_rh")
        if nxt in (None, "") or run_hours is None:
            return False
        return float(run_hours) >= float(nxt) - meter_window(plan.get("interval_rh"))
    nxt = parse_date(plan.get("next_due_date"))
    if not nxt:
        return False
    return (nxt - today).days <= int(plan.get("lead_days") or 7)


def next_due_after_completion(plan, done_date, done_rh=None):
    """Plan fields to update after a work order of the plan is completed (time: from work date; meter: from run hours)."""
    if plan.get("strategy") == "meter":
        if done_rh is None:
            raise ValueError("Run hours at completion are required for a run-hours plan")
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
    base = parse_date(wo.get("due_date")) or parse_date(plan.get("next_due_date")) or today_ist()
    return {"next_due_date": (base + timedelta(days=days)).isoformat()}


def due_date_for_priority(priority, created=None):
    return ((created or today_ist()) + timedelta(days=PRIORITY_DAYS.get(priority, 7))).isoformat()


# ----------------------------------------------------------------------------- KPIs
def _day(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, IST).date() if ts_ms else None


def kpis(work_orders, start, end, today=None, run_hours=None):
    """SMRP-style KPIs over [start, end] (dates, inclusive).

    pm_compliance_pct  planned WOs due in the period that were completed on or before their due date
    backlog / overdue  open WOs now
    mttr_h             mean time to complete corrective WOs (created -> completed) completed in the period
    planned_pct        share of planned work among WOs completed in the period
    """
    today = today or today_ist()
    run_hours = run_hours or {}
    due_in, on_time = 0, 0
    done = []
    for w in work_orders:
        if w.get("status") == CANCELLED:
            continue
        due = parse_date(w.get("due_date"))
        completed = _day(w.get("completed_ts"))
        if w.get("type") in PLANNED_TYPES and due and start <= due <= end:
            due_in += 1
            if completed and completed <= due:
                on_time += 1
        if completed and start <= completed <= end:
            done.append(w)
    corrective = [w for w in done if w.get("type") in ("Corrective", "Condition-based")]
    mttr = [(w["completed_ts"] - w["created_ts"]) / 3600000 for w in corrective if w.get("created_ts") and w.get("completed_ts")]
    open_wos = [w for w in work_orders if w.get("status") in OPEN]
    overdue = [w for w in open_wos if due_state(w, run_hours.get(w.get("equipment_id")), today) == "overdue"]
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
